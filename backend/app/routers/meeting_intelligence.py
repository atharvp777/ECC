"""
Endpoints for meeting transcription + AI summarization.

POST /meetings/intelligence/summarize/{meeting_id}
    → summarize existing transcript on a meeting record

POST /meetings/intelligence/transcribe/{meeting_id}
    → upload audio, transcribe via Whisper, save transcript

POST /meetings/intelligence/pipeline/{meeting_id}
    → upload audio, transcribe, summarize, save everything + action items
"""

import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.config import settings
from app.models.meeting import Meeting, MeetingActionItem
from app.services.meeting_intelligence import (
    summarize_transcript, transcribe_audio, full_pipeline, SUPPORTED_AUDIO
)

router = APIRouter(prefix="/meetings/intelligence", tags=["meeting-intelligence"])

AUDIO_DIR = settings.UPLOADS_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _save_upload(file: UploadFile) -> Path:
    ext  = Path(file.filename).suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"
    dest = AUDIO_DIR / name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dest


def _apply_summary_to_meeting(meeting: Meeting, result: dict, db: Session):
    """Write AI results back to the meeting record and create action items."""
    meeting.summary = result.get("summary", "")

    # Append key decisions to summary if present
    decisions = result.get("key_decisions", [])
    if decisions:
        meeting.summary += "\n\n**Key Decisions:**\n" + "\n".join(f"- {d}" for d in decisions)

    topics = result.get("topics_discussed", [])
    if topics:
        meeting.summary += "\n\n**Topics:** " + ", ".join(topics)

    # Preserve manual items and avoid re-adding the same AI suggestion when a
    # meeting is summarized again. V2 will add provenance to replace generated
    # items as a group without touching manual action items.
    existing_descriptions = {
        " ".join(item.description.lower().split())
        for item in meeting.action_items
    }
    for item in result.get("action_items", []):
        description = (item.get("description") or "").strip()
        normalized_description = " ".join(description.lower().split())
        if not normalized_description or normalized_description in existing_descriptions:
            continue
        due = None
        if item.get("due_date"):
            try:
                due = datetime.strptime(item["due_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        ai = MeetingActionItem(
            description=description,
            assignee=item.get("assignee"),
            due_date=due,
            meeting_id=meeting.id,
        )
        db.add(ai)
        existing_descriptions.add(normalized_description)

    db.commit()
    db.refresh(meeting)
    return meeting


# ── Endpoints ─────────────────────────────────────────────────────────────────

class SummarizeResponse(BaseModel):
    meeting_id: int
    summary: str
    action_items_created: int


@router.post("/summarize/{meeting_id}", response_model=SummarizeResponse)
def summarize_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """
    Summarize an existing meeting that already has raw_transcript set.
    Writes the summary + action items back to the DB.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not meeting.raw_transcript:
        raise HTTPException(status_code=400, detail="Meeting has no transcript. Add one first.")

    try:
        result = summarize_transcript(meeting.raw_transcript, meeting.attendees or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {e}")

    meeting = _apply_summary_to_meeting(meeting, result, db)
    return SummarizeResponse(
        meeting_id=meeting_id,
        summary=meeting.summary or "",
        action_items_created=len(result.get("action_items", [])),
    )


@router.post("/transcribe/{meeting_id}")
async def transcribe_meeting_audio(
    meeting_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload audio → Whisper → save transcript to meeting. Does NOT summarize."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_AUDIO:
        raise HTTPException(status_code=400, detail=f"Unsupported format {ext}. Use: {SUPPORTED_AUDIO}")

    audio_path = _save_upload(file)
    try:
        transcript = transcribe_audio(str(audio_path))
    except Exception as e:
        audio_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    meeting.raw_transcript = transcript
    db.commit()
    return {"meeting_id": meeting_id, "transcript": transcript, "length": len(transcript)}


@router.post("/pipeline/{meeting_id}", response_model=SummarizeResponse)
async def full_meeting_pipeline(
    meeting_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload audio → Whisper → GPT summary → save everything. One shot."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_AUDIO:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

    audio_path = _save_upload(file)
    try:
        result = full_pipeline(str(audio_path), meeting.attendees or "")
    except Exception as e:
        audio_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    meeting.raw_transcript = result.get("transcript", "")
    meeting = _apply_summary_to_meeting(meeting, result, db)

    return SummarizeResponse(
        meeting_id=meeting_id,
        summary=meeting.summary or "",
        action_items_created=len(result.get("action_items", [])),
    )

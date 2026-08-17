"""
Meeting Intelligence service.

Features:
  1. transcribe_audio(file_path) → raw transcript text via OpenAI Whisper API
  2. summarize_transcript(transcript, attendees) → {summary, action_items[]}
  3. full_pipeline(file_path, attendees) → transcribe + summarize in one call
"""

import json
import re
from pathlib import Path
from typing import Optional

from app.core.config import settings

SUPPORTED_AUDIO = {".mp3", ".mp4", ".m4a", ".wav", ".webm", ".ogg", ".flac"}


def _get_client():
    from groq import Groq
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not configured in .env")
    return Groq(api_key=settings.GROQ_API_KEY)


# ── 1. Transcription ──────────────────────────────────────────────────────────

def transcribe_audio(file_path: str) -> str:
    """
    Transcribe audio using Groq's Whisper endpoint (free).
    Supports: mp3, mp4, m4a, wav, webm, ogg, flac (max 25 MB).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO:
        raise ValueError(f"Unsupported audio format: {path.suffix}")

    client = _get_client()
    with open(path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            response_format="text",
        )
    return str(response)


# ── 2. Summarization ──────────────────────────────────────────────────────────

SUMMARY_PROMPT = """You are an expert meeting analyst. Given the meeting transcript below, produce a structured JSON response.

Meeting attendees: {attendees}

Your response must be ONLY valid JSON, no markdown, no backticks, exactly this shape:
{{
  "summary": "3-5 sentence executive summary of the meeting",
  "key_decisions": ["decision 1", "decision 2"],
  "action_items": [
    {{
      "description": "what needs to be done",
      "assignee": "person's name or null if unassigned",
      "due_date": "YYYY-MM-DD or null if not mentioned"
    }}
  ],
  "topics_discussed": ["topic 1", "topic 2", "topic 3"]
}}

TRANSCRIPT:
{transcript}"""


def summarize_transcript(transcript: str, attendees: str = "") -> dict:
    """
    Use the active AI provider to extract summary and action items from a transcript.
    Returns dict with: summary, key_decisions, action_items, topics_discussed
    """
    if not transcript.strip():
        return {
            "summary": "",
            "key_decisions": [],
            "action_items": [],
            "topics_discussed": [],
        }

    from app.services.ai_providers import complete_text

    prompt = SUMMARY_PROMPT.format(
        attendees=attendees or "Not specified",
        transcript=transcript[:12000],   # ~3000 tokens max input
    )

    raw = complete_text(
        system=prompt,
        messages=[],
        max_tokens=1500,
        temperature=0.3,
    ).strip()

    # Strip markdown fences if model adds them anyway
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback — return just the raw text as summary
        return {
            "summary": raw,
            "key_decisions": [],
            "action_items": [],
            "topics_discussed": [],
        }


# ── 3. Full pipeline ──────────────────────────────────────────────────────────

def full_pipeline(file_path: str, attendees: str = "") -> dict:
    """Transcribe audio → summarize → return everything."""
    transcript = transcribe_audio(file_path)
    result     = summarize_transcript(transcript, attendees)
    result["transcript"] = transcript
    return result

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.meeting import Meeting, MeetingActionItem
from app.schemas.meeting import (
    MeetingCreate, MeetingUpdate, MeetingRead,
    ActionItemCreate, ActionItemUpdate, ActionItemRead,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("/", response_model=list[MeetingRead])
def list_meetings(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Meeting)
    if project_id is not None:
        query = query.filter(Meeting.project_id == project_id)
    return query.order_by(Meeting.held_at.desc()).all()


@router.post("/", response_model=MeetingRead, status_code=status.HTTP_201_CREATED)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"action_items"})
    meeting = Meeting(**data)
    db.add(meeting)
    db.flush()  # Get meeting.id before committing

    for item_data in payload.action_items:
        item = MeetingActionItem(**item_data.model_dump(), meeting_id=meeting.id)
        db.add(item)

    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingRead)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.patch("/{meeting_id}", response_model=MeetingRead)
def update_meeting(meeting_id: int, payload: MeetingUpdate, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(meeting, field, value)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    db.delete(meeting)
    db.commit()


# --- Action Items sub-routes ---

@router.post("/{meeting_id}/action-items", response_model=ActionItemRead, status_code=status.HTTP_201_CREATED)
def add_action_item(meeting_id: int, payload: ActionItemCreate, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    item = MeetingActionItem(**payload.model_dump(), meeting_id=meeting_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{meeting_id}/action-items/{item_id}", response_model=ActionItemRead)
def update_action_item(
    meeting_id: int, item_id: int, payload: ActionItemUpdate, db: Session = Depends(get_db)
):
    item = (
        db.query(MeetingActionItem)
        .filter(MeetingActionItem.id == item_id, MeetingActionItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{meeting_id}/action-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_item(meeting_id: int, item_id: int, db: Session = Depends(get_db)):
    item = (
        db.query(MeetingActionItem)
        .filter(MeetingActionItem.id == item_id, MeetingActionItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    db.delete(item)
    db.commit()

from pydantic import BaseModel, ConfigDict
from datetime import datetime


# --- Action Items ---

class ActionItemBase(BaseModel):
    description: str
    assignee: str | None = None
    due_date: datetime | None = None
    is_done: bool = False


class ActionItemCreate(ActionItemBase):
    pass


class ActionItemUpdate(BaseModel):
    description: str | None = None
    assignee: str | None = None
    due_date: datetime | None = None
    is_done: bool | None = None


class ActionItemRead(ActionItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    meeting_id: int


# --- Meetings ---

class MeetingBase(BaseModel):
    title: str
    held_at: datetime
    attendees: str | None = None
    agenda: str | None = None
    summary: str | None = None
    raw_transcript: str | None = None
    project_id: int | None = None


class MeetingCreate(MeetingBase):
    action_items: list[ActionItemCreate] = []


class MeetingUpdate(BaseModel):
    title: str | None = None
    held_at: datetime | None = None
    attendees: str | None = None
    agenda: str | None = None
    summary: str | None = None
    raw_transcript: str | None = None
    project_id: int | None = None


class MeetingRead(MeetingBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    action_items: list[ActionItemRead] = []

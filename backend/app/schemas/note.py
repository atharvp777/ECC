from pydantic import BaseModel, ConfigDict
from datetime import datetime


class NoteBase(BaseModel):
    title: str
    content: str = ""
    tags: str | None = None
    project_id: int | None = None


class NoteCreate(NoteBase):
    pass


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: str | None = None
    project_id: int | None = None


class NoteRead(NoteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

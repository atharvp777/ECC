from pydantic import BaseModel, ConfigDict
from datetime import datetime


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    title: str | None
    description: str | None
    tags: str | None
    project_id: int | None
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: str | None = None
    project_id: int | None = None

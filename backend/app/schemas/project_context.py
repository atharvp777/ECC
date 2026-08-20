from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime

# Upper bound for a single durable fact. Content is DATA, so the limit is a
# size guard, never a semantic constraint.
MAX_CONTENT_CHARS = 2000


def _normalize_content(v: str) -> str:
    text = (v or "").strip()
    if not text:
        raise ValueError("content must not be empty")
    if len(text) > MAX_CONTENT_CHARS:
        raise ValueError(f"content must be at most {MAX_CONTENT_CHARS} characters")
    return text


class ProjectContextBase(BaseModel):
    content: str
    category: str | None = None

    @field_validator("content")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        return _normalize_content(v)


class ProjectContextCreate(ProjectContextBase):
    source: str | None = None


class ProjectContextUpdate(BaseModel):
    content: str | None = None
    category: str | None = None
    active: bool | None = None

    @field_validator("content")
    @classmethod
    def _validate_content(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _normalize_content(v)


class ProjectContextRead(ProjectContextBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
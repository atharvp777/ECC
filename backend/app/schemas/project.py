from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime
from app.core.timeutil import normalize_to_system
from app.models.project import ProjectCategory, ProjectStatus


class ProjectBase(BaseModel):
    name: str
    description: str | None = None
    category: ProjectCategory = ProjectCategory.PERSONAL
    status: ProjectStatus = ProjectStatus.ACTIVE
    deadline: datetime | None = None
    color: str = "#6366f1"

    @field_validator("deadline")
    @classmethod
    def _normalize_deadline(cls, v: datetime | None) -> datetime | None:
        return normalize_to_system(v)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: ProjectCategory | None = None
    status: ProjectStatus | None = None
    deadline: datetime | None = None
    color: str | None = None

    @field_validator("deadline")
    @classmethod
    def _normalize_deadline(cls, v: datetime | None) -> datetime | None:
        return normalize_to_system(v)


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    task_count: int = 0
    done_tasks: int = 0


class ProjectReadWithStats(ProjectRead):
    total_tasks: int = 0
    done_tasks: int = 0
    overdue_tasks: int = 0

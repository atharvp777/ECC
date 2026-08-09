from pydantic import BaseModel, ConfigDict
from datetime import datetime
from app.models.task import TaskPriority, TaskStatus


class TaskBase(BaseModel):
    title: str
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.TODO
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    is_recurring: bool = False
    recurrence_rule: str | None = None
    project_id: int | None = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    actual_minutes: int | None = None
    is_recurring: bool | None = None
    recurrence_rule: str | None = None
    project_id: int | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actual_minutes: int | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

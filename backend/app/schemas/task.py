from pydantic import BaseModel, ConfigDict
from datetime import datetime
from app.models.task import TaskPriority, TaskStatus, TaskType


class TaskBase(BaseModel):
    title: str
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.TODO
    task_type: TaskType = TaskType.WORK
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    is_recurring: bool = False
    recurrence_rule: str | None = None
    project_id: int | None = None


class TaskCreate(TaskBase):
    # Calendar scheduling (optional). scheduled_start/end are the "when the
    # user intends to work on the task" times, distinct from `deadline`.
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    schedule_on_calendar: bool = False
    when: str | None = None
    start_time: str | None = None
    duration_minutes: int = 60


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    task_type: TaskType | None = None
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    actual_minutes: int | None = None
    is_recurring: bool | None = None
    recurrence_rule: str | None = None
    project_id: int | None = None
    # Calendar scheduling (optional)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    schedule_on_calendar: bool = False
    when: str | None = None
    start_time: str | None = None
    duration_minutes: int = 60


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actual_minutes: int | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    # Calendar scheduling state (server-owned; the client never supplies an ID)
    google_calendar_event_id: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    calendar_sync_error: str | None = None

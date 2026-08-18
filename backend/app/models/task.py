from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Enum as SAEnum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum

from app.core.database import Base


class TaskPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class TaskType(str, enum.Enum):
    """What kind of task this is. Meetings are stored as tasks (task_type=meeting)
    so reminders can also be linked to Google Calendar."""

    WORK = "work"
    REMINDER = "reminder"
    MEETING = "meeting"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(
            TaskPriority,
            values_callable=lambda x: [e.value for e in x],
            validate_strings=True,
        ),
        default=TaskPriority.MEDIUM,
    )
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(
            TaskStatus,
            values_callable=lambda x: [e.value for e in x],
            validate_strings=True,
        ),
        default=TaskStatus.TODO,
    )
    task_type: Mapped[TaskType] = mapped_column(
        SAEnum(
            TaskType,
            values_callable=lambda x: [e.value for e in x],
            validate_strings=True,
        ),
        default=TaskType.WORK,
    )

    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Google Calendar scheduling.
    #   deadline       = "when the task is due"
    #   scheduled_*    = "when the user intends to work on the task"
    # The existence of google_calendar_event_id is the sync state; there is no
    # separate calendar_synced flag.
    google_calendar_event_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    scheduled_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    calendar_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. "daily", "weekly"

    # FK to project (optional — tasks can exist without a project)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    project: Mapped["Project | None"] = relationship("Project", back_populates="tasks")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} status={self.status}>"

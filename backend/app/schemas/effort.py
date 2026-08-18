"""Pydantic schemas for task effort estimation (Step 5).

``TaskEffortContext`` is the deterministic snapshot the read-only estimation
tool gathers about a task. ``EffortEstimate`` is the model's structured
proposal — a recommendation only, never a database write.
"""

from pydantic import BaseModel
from datetime import datetime

from app.models.task import TaskPriority, TaskStatus, TaskType


class TaskEffortContext(BaseModel):
    task_id: int
    title: str
    description: str | None = None
    project_name: str | None = None
    priority: TaskPriority
    task_type: TaskType
    status: TaskStatus
    deadline: datetime | None = None
    existing_estimate_minutes: int | None = None


class EffortEstimate(BaseModel):
    task_id: int
    task_title: str
    estimated_minutes: int | None = None
    confidence: str = "low"  # "high" | "medium" | "low"
    reasoning: str = ""

    @property
    def is_proposal(self) -> bool:
        return self.estimated_minutes is not None and self.estimated_minutes > 0
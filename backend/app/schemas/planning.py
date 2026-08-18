"""Pydantic schemas for the deterministic Today planning overview.

Semantics (calendar-day based, deliberately different from /dashboard/stats):
  overdue    = deadline <  start_of_today
  due_today  = start_of_today <= deadline < start_of_tomorrow
A task due earlier today stays under "due today", never "overdue".
"""

from pydantic import BaseModel
from datetime import datetime

from app.models.task import TaskPriority, TaskStatus
from app.models.project import ProjectStatus


class PlanningTask(BaseModel):
    task_id: int
    title: str
    priority: TaskPriority
    status: TaskStatus
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    project_id: int | None = None
    project_name: str | None = None


class FocusCandidate(BaseModel):
    task_id: int
    title: str
    priority: TaskPriority
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    project_id: int | None = None
    project_name: str | None = None
    reasons: list[str]


class ProjectDeadline(BaseModel):
    project_id: int
    name: str
    deadline: datetime | None = None
    status: ProjectStatus
    total_tasks: int = 0
    done_tasks: int = 0
    progress: float = 0.0


class WorkloadSummary(BaseModel):
    total_open_tasks: int = 0
    overdue_count: int = 0
    due_today_count: int = 0
    upcoming_count: int = 0
    # Unfinished tasks with priority == critical (matches /dashboard/stats).
    critical_count: int = 0
    # Sum of estimated_minutes for unfinished tasks due today (NULL treated as 0).
    estimated_minutes_today: int = 0


class CalendarEventInfo(BaseModel):
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None


class FreeWindow(BaseModel):
    start: datetime
    end: datetime
    duration_minutes: int


class CalendarOverview(BaseModel):
    connected: bool = False
    events: list[CalendarEventInfo] = []
    free_windows: list[FreeWindow] = []


class PlanningTasks(BaseModel):
    overdue: list[PlanningTask] = []
    due_today: list[PlanningTask] = []
    upcoming: list[PlanningTask] = []
    critical: list[PlanningTask] = []


class PlanningProjects(BaseModel):
    deadlines: list[ProjectDeadline] = []


class TodayOverview(BaseModel):
    generated_at: datetime
    timezone: str
    tasks: PlanningTasks
    focus_candidates: list[FocusCandidate] = []
    projects: PlanningProjects
    workload: WorkloadSummary
    calendar: CalendarOverview

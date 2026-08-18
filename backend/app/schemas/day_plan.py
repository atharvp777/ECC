"""Pydantic schemas for the deterministic Day Plan.

A DayPlan is a pure recommendation produced by the day planner service from a
TodayOverview. It never mutates state: no calendar events are created, no
tasks are changed, nothing is written back. The scheduled blocks only fill the
free windows the planning service actually computed, so calendar events are
always respected.
"""

from pydantic import BaseModel
from datetime import datetime

from app.models.task import TaskPriority


class ScheduledBlock(BaseModel):
    task_id: int
    title: str
    project: str | None = None
    start: datetime
    end: datetime
    duration_minutes: int
    reasons: list[str] = []


class UnscheduledTask(BaseModel):
    task_id: int
    title: str
    estimated_minutes: int | None = None
    priority: TaskPriority
    deadline: datetime | None = None
    reason: str


class UnusedWindow(BaseModel):
    start: datetime
    end: datetime
    duration_minutes: int


class DayPlanSummary(BaseModel):
    total_tasks: int = 0
    scheduled_tasks: int = 0
    unscheduled_tasks: int = 0
    total_scheduled_minutes: int = 0
    total_available_minutes: int = 0
    unused_minutes: int = 0
    calendar_connected: bool = False


class DayPlan(BaseModel):
    date: str
    timezone: str
    generated_at: datetime
    scheduled_blocks: list[ScheduledBlock] = []
    unscheduled_tasks: list[UnscheduledTask] = []
    unused_windows: list[UnusedWindow] = []
    summary: DayPlanSummary
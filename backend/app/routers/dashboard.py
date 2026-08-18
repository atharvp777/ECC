from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from app.core.database import get_db
from app.core.timeutil import SYSTEM_TIMEZONE, normalize_to_system
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskStatus, TaskPriority

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardStats(BaseModel):
    total_projects: int
    active_projects: int
    total_tasks: int
    done_tasks: int
    overdue_tasks: int
    due_today: int
    critical_tasks: int
    tasks_this_week: int


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    now = normalize_to_system(datetime.now(timezone.utc))
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    end_of_week = now + timedelta(days=7)

    total_projects = db.query(func.count(Project.id)).scalar() or 0
    active_projects = (
        db.query(func.count(Project.id))
        .filter(Project.status == ProjectStatus.ACTIVE)
        .scalar() or 0
    )
    total_tasks = db.query(func.count(Task.id)).scalar() or 0
    done_tasks = (
        db.query(func.count(Task.id)).filter(Task.status == TaskStatus.DONE).scalar() or 0
    )
    overdue_tasks = (
        db.query(func.count(Task.id))
        .filter(Task.deadline < now, Task.status != TaskStatus.DONE)
        .scalar() or 0
    )
    due_today = (
        db.query(func.count(Task.id))
        .filter(
            Task.deadline >= start_of_today,
            Task.deadline <= end_of_today,
            Task.status != TaskStatus.DONE,
        )
        .scalar() or 0
    )
    critical_tasks = (
        db.query(func.count(Task.id))
        .filter(Task.priority == TaskPriority.CRITICAL, Task.status != TaskStatus.DONE)
        .scalar() or 0
    )
    tasks_this_week = (
        db.query(func.count(Task.id))
        .filter(
            Task.deadline >= now,
            Task.deadline <= end_of_week,
            Task.status != TaskStatus.DONE,
        )
        .scalar() or 0
    )

    return DashboardStats(
        total_projects=total_projects,
        active_projects=active_projects,
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        overdue_tasks=overdue_tasks,
        due_today=due_today,
        critical_tasks=critical_tasks,
        tasks_this_week=tasks_this_week,
    )

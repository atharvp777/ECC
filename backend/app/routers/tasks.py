from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel

from app.core.database import get_db
from app.models.task import Task, TaskStatus, TaskPriority
from app.models.project import Project
from app.schemas.task import TaskCreate, TaskUpdate, TaskRead
from app.services.tools import (
    build_calendar_event_body,
    parse_event_datetime,
    sync_task_to_calendar,
)
from app.services.task_calendar_sync import (
    delete_event_best_effort,
    unlink_event,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

SYSTEM_TIMEZONE = "Asia/Kolkata"


class TaskCalendarRequest(BaseModel):
    """Request body for POST /tasks/{id}/calendar.

    Accepts either concrete datetimes (scheduled_start/end) or the
    natural-language when/start_time phrases resolved server-side.
    """
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    when: str | None = None
    start_time: str | None = None
    duration_minutes: int = 60
    timezone: str = SYSTEM_TIMEZONE


def _normalize_tz(dt: datetime, tz_name: str = SYSTEM_TIMEZONE) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(ZoneInfo(tz_name))


def _apply_filters(query, project_id, status_filter, priority_filter):
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if status_filter:
        query = query.filter(Task.status == status_filter)
    if priority_filter:
        query = query.filter(Task.priority == priority_filter)
    return query


@router.get("/", response_model=list[TaskRead])
def list_tasks(
    project_id: int | None = Query(None),
    status: TaskStatus | None = Query(None),
    priority: TaskPriority | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Task)
    query = _apply_filters(query, project_id, status, priority)
    return query.order_by(Task.deadline.asc().nullslast(), Task.created_at.desc()).all()


@router.get("/today", response_model=list[TaskRead])
def get_todays_tasks(db: Session = Depends(get_db)):
    """Returns tasks due today or overdue and not yet done."""
    now = datetime.now(timezone.utc)
    end_of_today = now.replace(hour=23, minute=59, second=59)
    tasks = (
        db.query(Task)
        .filter(
            Task.status != TaskStatus.DONE,
            Task.deadline <= end_of_today,
        )
        .order_by(Task.priority.asc(), Task.deadline.asc())
        .all()
    )
    return tasks


@router.get("/upcoming", response_model=list[TaskRead])
def get_upcoming_tasks(days: int = Query(7), db: Session = Depends(get_db)):
    """Returns tasks due in the next N days."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=days)
    tasks = (
        db.query(Task)
        .filter(
            Task.status != TaskStatus.DONE,
            Task.deadline >= now,
            Task.deadline <= future,
        )
        .order_by(Task.deadline.asc())
        .all()
    )
    return tasks


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    if payload.project_id is not None:
        project = db.query(Project).filter(Project.id == payload.project_id).first()
        if not project:
            raise HTTPException(
                status_code=400,
                detail=f"Project {payload.project_id} does not exist",
            )

    data = payload.model_dump()
    schedule_on_calendar = data.pop("schedule_on_calendar", False)
    when = data.pop("when", None)
    start_time = data.pop("start_time", None)
    duration_minutes = data.pop("duration_minutes", None) or 60

    # Normalize scheduling datetimes to the system timezone.
    if data.get("scheduled_start") is not None:
        data["scheduled_start"] = _normalize_tz(data["scheduled_start"])
        if data.get("scheduled_end") is None:
            data["scheduled_end"] = data["scheduled_start"] + timedelta(minutes=duration_minutes)
    if data.get("scheduled_end") is not None:
        data["scheduled_end"] = _normalize_tz(data["scheduled_end"])

    task = Task(**data)
    db.add(task)
    db.commit()
    db.refresh(task)

    # The task is committed first. Calendar sync is best-effort: on failure the
    # task stays and calendar_sync_error is populated. Never roll back.
    if schedule_on_calendar:
        if task.scheduled_start is None:
            body = build_calendar_event_body({
                "summary": task.title,
                "description": task.description,
                "when": when,
                "start_time": start_time,
                "duration_minutes": duration_minutes,
                "timezone": SYSTEM_TIMEZONE,
            })
            task.scheduled_start = parse_event_datetime(body["start"]["dateTime"])
            task.scheduled_end = parse_event_datetime(body["end"]["dateTime"])
            db.commit()
            db.refresh(task)
        sync_task_to_calendar(db, task, schedule_on_calendar=True)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = payload.model_dump(exclude_unset=True)

    if updates.get("project_id") is not None:
        project = db.query(Project).filter(Project.id == updates["project_id"]).first()
        if not project:
            raise HTTPException(
                status_code=400,
                detail=f"Project {updates['project_id']} does not exist",
            )

    # Auto-set completed_at when marking done. Completed tasks keep their
    # linked calendar event (no automatic deletion).
    if updates.get("status") == TaskStatus.DONE and task.status != TaskStatus.DONE:
        updates["completed_at"] = datetime.now(timezone.utc)
    elif updates.get("status") and updates["status"] != TaskStatus.DONE:
        updates["completed_at"] = None

    # Calendar scheduling control fields are handled below, not set as columns.
    schedule_on_calendar = updates.pop("schedule_on_calendar", None)
    when = updates.pop("when", None)
    start_time = updates.pop("start_time", None)
    duration_minutes = updates.pop("duration_minutes", None) or 60

    # Resolve scheduling datetimes (server-side, system timezone).
    if updates.get("scheduled_start") is not None or (when or start_time):
        if updates.get("scheduled_start") is not None:
            start = _normalize_tz(updates["scheduled_start"])
            end = updates.get("scheduled_end")
            if end is not None:
                end = _normalize_tz(end)
            else:
                end = start + timedelta(minutes=duration_minutes)
            updates["scheduled_start"] = start
            updates["scheduled_end"] = end
        else:
            body = build_calendar_event_body({
                "summary": task.title,
                "when": when,
                "start_time": start_time,
                "duration_minutes": duration_minutes,
                "timezone": SYSTEM_TIMEZONE,
            })
            updates["scheduled_start"] = parse_event_datetime(body["start"]["dateTime"])
            updates["scheduled_end"] = parse_event_datetime(body["end"]["dateTime"])

    title_changed = "title" in updates
    schedule_changed = "scheduled_start" in updates or "scheduled_end" in updates

    for field, value in updates.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)

    # Sync the linked calendar event when the schedule/title changed or an
    # explicit calendar sync was requested. Never creates a duplicate.
    sync_task_to_calendar(
        db, task,
        schedule_on_calendar=bool(schedule_on_calendar),
        when=when, start_time=start_time, duration_minutes=duration_minutes,
        schedule_changed=schedule_changed, title_changed=title_changed,
    )
    return task


@router.post("/{task_id}/calendar", response_model=TaskRead)
def link_task_to_calendar(task_id: int, payload: TaskCalendarRequest, db: Session = Depends(get_db)):
    """Link an existing task to Google Calendar (idempotent).

    If the task already has google_calendar_event_id the existing event is
    updated, never duplicated.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if payload.scheduled_start is not None:
        task.scheduled_start = _normalize_tz(payload.scheduled_start, payload.timezone)
        if payload.scheduled_end is not None:
            task.scheduled_end = _normalize_tz(payload.scheduled_end, payload.timezone)
        else:
            task.scheduled_end = task.scheduled_start + timedelta(
                minutes=payload.duration_minutes or 60
            )
    elif payload.when or payload.start_time:
        body = build_calendar_event_body({
            "summary": task.title,
            "description": task.description,
            "when": payload.when,
            "start_time": payload.start_time,
            "duration_minutes": payload.duration_minutes,
            "timezone": payload.timezone,
        })
        task.scheduled_start = parse_event_datetime(body["start"]["dateTime"])
        task.scheduled_end = parse_event_datetime(body["end"]["dateTime"])
    db.commit()
    db.refresh(task)

    sync_task_to_calendar(
        db, task, schedule_on_calendar=True, timezone=payload.timezone,
    )
    return task


@router.delete("/{task_id}/calendar", response_model=TaskRead)
def unlink_task_from_calendar(task_id: int, db: Session = Depends(get_db)):
    """Remove the linked Google event but keep the ECC task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    unlink_event(db, task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Best-effort: attempt to delete the linked Google event, but never block
    # task deletion on Google availability.
    delete_event_best_effort(task)
    db.delete(task)
    db.commit()
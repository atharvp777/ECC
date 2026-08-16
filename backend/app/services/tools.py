from pydantic import BaseModel
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import re
from app.models import Project, Task
from app.models.project import ProjectCategory
from app.services.google_calendar import (
    get_upcoming_events as gc_get_upcoming_events,
    create_calendar_event as gc_create_calendar_event,
    update_calendar_event as gc_update_calendar_event,
    delete_calendar_event as gc_delete_calendar_event,
)


# ---------- Request schemas ----------
class ListProjectsRequest(BaseModel):
    pass


class CreateProjectRequest(BaseModel):
    name: str
    category: str | None = None


class UpdateProjectRequest(BaseModel):
    project_id: int
    name: Optional[str] = None
    category: Optional[str] = None


class ListTasksRequest(BaseModel):
    pass


class CreateTaskRequest(BaseModel):
    title: str
    priority: str = "MEDIUM"
    deadline: Optional[str] = None
    project_id: Optional[int] = None


class UpdateTaskRequest(BaseModel):
    task_id: int
    title: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[str] = None
    project_id: Optional[int] = None
    status: Optional[str] = None


class CompleteTaskRequest(BaseModel):
    task_id: int


class ListCalendarEventsRequest(BaseModel):
    pass


class CreateCalendarEventRequest(BaseModel):
    event_data: Dict[str, Any]


class UpdateCalendarEventRequest(BaseModel):
    event_id: str
    event_data: Dict[str, Any]


class DeleteCalendarEventRequest(BaseModel):
    event_id: str


# ---------- Calendar event body resolution (deterministic, server-side) ----------
# The system timezone is UTC+05:30. The planner never guesses "now"; it passes a
# natural-language `when` phrase and the server resolves the concrete datetime.
SYSTEM_TIMEZONE = "Asia/Kolkata"
DEFAULT_EVENT_HOUR = 9
DEFAULT_DURATION_MINUTES = 60

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _parse_time(phrase: str) -> Optional[tuple]:
    """Extract (hour, minute) from 'HH:MM' or '3pm' style text, or None."""
    if not phrase:
        return None
    match = re.search(r"(\d{1,2}):(\d{2})", phrase)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    match = re.search(r"(\d{1,2})\s*(am|pm)", phrase.lower())
    if match:
        hour = int(match.group(1)) % 12
        if match.group(2) == "pm":
            hour += 12
        return (hour, 0)
    return None


def _resolve_event_date(when: str, now: datetime) -> date:
    """Resolve a natural-language date phrase against the server clock."""
    text = (when or "").strip().lower()
    if not text:
        return now.date()

    # Full date embedded anywhere in the phrase: 2026-08-20 or 2026-08-20T10:00:00
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    if "today" in text:
        return now.date()
    if "tomorrow" in text:
        return now.date() + timedelta(days=1)

    for name, index in _WEEKDAYS.items():
        if name in text:
            if "next" in text:
                days_ahead = (index - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
            else:
                days_ahead = (index - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
            return now.date() + timedelta(days=days_ahead)

    return now.date()


def _resolve_event_datetime(args: Dict[str, Any], now: datetime) -> datetime:
    """Combine when + start_time into a timezone-aware start datetime."""
    when = (args.get("when") or "").strip()
    start_time = (args.get("start_time") or "").strip()

    # Honor a full ISO datetime passed directly in `when`.
    full = re.search(
        r"(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?",
        when,
    )
    if full and not start_time:
        return datetime(
            int(full.group(1)), int(full.group(2)), int(full.group(3)),
            int(full.group(4)), int(full.group(5)),
            int(full.group(6) or 0),
            tzinfo=now.tzinfo,
        )

    parsed_time = _parse_time(start_time) or _parse_time(when) or (DEFAULT_EVENT_HOUR, 0)
    event_date = _resolve_event_date(when, now)
    return datetime.combine(event_date, time(parsed_time[0], parsed_time[1]), tzinfo=now.tzinfo)


def build_calendar_event_body(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build a Google Calendar API event body from planner-style arguments.

    Supports, in order of precedence:
      1. A complete `event_data` body passed through verbatim (existing contract).
      2. Structured `start`/`end` objects passed directly.
      3. `summary` + `when`/`start_time`/`duration_minutes` resolved server-side.
    """
    if isinstance(args.get("event_data"), dict):
        return dict(args["event_data"])

    if isinstance(args.get("start"), dict) and isinstance(args.get("end"), dict):
        body = {k: v for k, v in args.items() if k in ("summary", "description", "start", "end", "location")}
        return body

    tz_name = args.get("timezone") or SYSTEM_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(SYSTEM_TIMEZONE)
        tz_name = SYSTEM_TIMEZONE

    now = datetime.now(tz)
    start = _resolve_event_datetime(args, now)
    duration = int(args.get("duration_minutes") or DEFAULT_DURATION_MINUTES)
    if duration <= 0:
        duration = DEFAULT_DURATION_MINUTES
    end = start + timedelta(minutes=duration)

    body: Dict[str, Any] = {"summary": (args.get("summary") or "").strip() or "(no title)"}
    if args.get("description"):
        body["description"] = str(args["description"])
    body["start"] = {"dateTime": start.isoformat(), "timeZone": tz_name}
    body["end"] = {"dateTime": end.isoformat(), "timeZone": tz_name}
    return body


# ---------- Wrapper implementations ----------
def _normalize_project_category(category: str | ProjectCategory | None) -> str:
    if category is None:
        return ProjectCategory.PERSONAL.value
    if isinstance(category, ProjectCategory):
        return category.value

    normalized = str(category).strip().lower()
    for member in ProjectCategory:
        if normalized in {member.name.lower(), member.value.lower()}:
            return member.value

    raise ValueError(
        "Invalid project category. Use one of: baja, agrovault, college, personal, internship."
    )


def _project_exists(db: Session, project_id: int) -> bool:
    return db.query(Project.id).filter(Project.id == project_id).first() is not None


def list_projects(db: Session, req: ListProjectsRequest) -> Dict[str, Any]:
    projects = db.query(Project).filter(Project.status == "ACTIVE").all()
    return {"data": projects}


def create_project(db: Session, req: CreateProjectRequest) -> Dict[str, Any]:
    category = _normalize_project_category(req.category)
    proj = Project(name=req.name, category=category, status="ACTIVE")
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return {"data": proj}


def update_project(db: Session, req: UpdateProjectRequest) -> Dict[str, Any]:
    proj = db.query(Project).filter(Project.id == req.project_id).first()
    if not proj:
        return {"data": None}
    if req.name:
        proj.name = req.name
    if req.category:
        proj.category = _normalize_project_category(req.category)
    db.commit()
    db.refresh(proj)
    return {"data": proj}


def list_tasks(db: Session, req: ListTasksRequest) -> Dict[str, Any]:
    tasks = db.query(Task).all()
    return {"data": tasks}


def create_task(db: Session, req: CreateTaskRequest) -> Dict[str, Any]:
    deadline = None

    if req.deadline:
        deadline = datetime.fromisoformat(
            req.deadline.replace("Z", "+00:00")
        )

    if req.project_id is not None and not _project_exists(db, req.project_id):
        return {"data": {"error": f"Project not found: {req.project_id}"}}

    task = Task(
        title=req.title,
        priority=req.priority,
        deadline=deadline,
        project_id=req.project_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"data": task}


def update_task(db: Session, req: UpdateTaskRequest) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    update_data = req.dict(exclude_unset=True)
    for field, value in update_data.items():
        if field == "deadline" and value is not None:
            # Convert ISO string to datetime; handle Z suffix for UTC
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            task.deadline = datetime.fromisoformat(value)
        elif field == "project_id" and value is not None:
            if not _project_exists(db, value):
                return {"data": {"error": f"Project not found: {value}"}}
            setattr(task, field, value)
        else:
            setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return {"data": task}


def complete_task(db: Session, req: CompleteTaskRequest) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    task.status = "DONE"
    db.commit()
    db.refresh(task)
    return {"data": task}


def list_calendar_events(db: Session, req: ListCalendarEventsRequest) -> Dict[str, Any]:
    events = gc_get_upcoming_events(days=7, max_results=20)
    return {"data": events}


def create_calendar_event(db: Session, req: CreateCalendarEventRequest) -> Dict[str, Any]:
    event = gc_create_calendar_event(req.event_data)
    return {"data": event}


def update_calendar_event(db: Session, req: UpdateCalendarEventRequest) -> Dict[str, Any]:
    updated = gc_update_calendar_event(req.event_id, req.event_data)
    return {"data": updated}


def delete_calendar_event(db: Session, req: DeleteCalendarEventRequest) -> Dict[str, Any]:
    gc_delete_calendar_event(req.event_id)
    return {"data": {"status": "deleted", "event_id": req.event_id}}

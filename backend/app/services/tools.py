from pydantic import BaseModel
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from app.models import Project, Task, TaskStatus, TaskPriority
from app.models.project import ProjectCategory, ProjectStatus
from app.models.task import TaskType
from app.core.timeutil import normalize_to_system
from app.services.google_calendar import (
    get_upcoming_events as gc_get_upcoming_events,
    create_calendar_event as gc_create_calendar_event,
    update_calendar_event as gc_update_calendar_event,
    delete_calendar_event as gc_delete_calendar_event,
)
from app.services.task_calendar_sync import (
    create_or_update_event as tcs_create_or_update_event,
    unlink_event as tcs_unlink_event,
    delete_event_best_effort as tcs_delete_event_best_effort,
    TASK_NOT_LINKED_MESSAGE,
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
    task_type: Optional[str] = "work"
    deadline: Optional[str] = None
    deadline_when: Optional[str] = None
    project_id: Optional[int] = None
    # Calendar scheduling (optional). `when`/`start_time` are the user's
    # verbatim phrases; the server resolves them in Asia/Kolkata.
    when: Optional[str] = None
    start_time: Optional[str] = None
    duration_minutes: int = 60
    schedule_on_calendar: bool = False


class UpdateTaskRequest(BaseModel):
    task_id: Optional[int] = None
    task_title: Optional[str] = None  # user's verbatim reference; resolved server-side
    title: Optional[str] = None
    priority: Optional[str] = None
    task_type: Optional[str] = None
    deadline: Optional[str] = None
    deadline_when: Optional[str] = None
    project_id: Optional[int] = None
    status: Optional[str] = None
    # Calendar scheduling (optional)
    when: Optional[str] = None
    start_time: Optional[str] = None
    duration_minutes: int = 60
    schedule_on_calendar: bool = False


class CompleteTaskRequest(BaseModel):
    task_id: Optional[int] = None
    task_title: Optional[str] = None  # user's verbatim reference; resolved server-side


class BulkUpdateTasksRequest(BaseModel):
    """Bulk task mutation request.

    Targets are chosen by explicit ``task_ids`` OR by a ``scope``
    (``all_open`` / ``overdue`` / ``critical``), optionally narrowed to a
    single ``project_id``. Every update is validated up-front so a bad id or
    value aborts the WHOLE operation — no partial mutations.
    """
    task_ids: Optional[list[int]] = None
    project_id: Optional[int] = None
    scope: Optional[str] = None  # "all_open" | "overdue" | "critical"
    status: Optional[str] = None
    priority: Optional[str] = None
    deadline_when: Optional[str] = None


class DeleteTaskRequest(BaseModel):
    task_id: Optional[int] = None
    task_title: Optional[str] = None  # user's verbatim reference; resolved server-side


class ListCalendarEventsRequest(BaseModel):
    pass


class CreateCalendarEventRequest(BaseModel):
    event_data: Dict[str, Any]


class UpdateCalendarEventRequest(BaseModel):
    event_id: str
    event_data: Dict[str, Any]


class DeleteCalendarEventRequest(BaseModel):
    event_id: str


class AddTaskToCalendarRequest(BaseModel):
    task_id: int
    when: Optional[str] = None
    start_time: Optional[str] = None
    duration_minutes: int = 60
    timezone: str = "Asia/Kolkata"


class RemoveTaskFromCalendarRequest(BaseModel):
    task_id: int


class GetTodayOverviewRequest(BaseModel):
    """Read-only current-state planning query. No arguments needed — the
    backend computes the IST calendar-day overview from the database and
    calendar API."""
    pass


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


def parse_event_datetime(value: str) -> datetime:
    """Parse an ISO dateTime produced by build_calendar_event_body()."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _has_explicit_schedule(args: Dict[str, Any]) -> bool:
    """True when a scheduling request carries an explicit date and/or time.

    A request with NO date and NO time (e.g. "put task X on my calendar") must
    never be silently defaulted to today at 09:00 — that can create a work slot
    in the past that disappears from the upcoming-calendar view. Callers return
    a clarification instead of inventing a time.
    """
    if isinstance(args.get("event_data"), dict):
        return True
    if isinstance(args.get("start"), dict) and isinstance(args.get("end"), dict):
        return True
    when = (args.get("when") or "").strip()
    start_time = (args.get("start_time") or "").strip()
    return bool(when or start_time)


def build_event_body_from_datetimes(
    start_dt: datetime,
    end_dt: datetime,
    summary: str,
    description: Optional[str] = None,
    timezone: str = SYSTEM_TIMEZONE,
) -> Dict[str, Any]:
    """Build a Google Calendar event body from concrete datetimes.

    Naive datetimes (e.g. re-loaded from SQLite, which does not preserve
    offsets) are interpreted as the system timezone so the event is never sent
    to Google as a floating (offset-less) time.
    """
    tz = ZoneInfo(timezone)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tz)
    else:
        start_dt = start_dt.astimezone(tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=tz)
    else:
        end_dt = end_dt.astimezone(tz)
    return {
        "summary": (summary or "").strip() or "(no title)",
        "description": description or None,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
    }


def resolve_task_schedule(
    update_data: Dict[str, Any],
    when: Optional[str] = None,
    start_time: Optional[str] = None,
    duration_minutes: int = 60,
    timezone: str = SYSTEM_TIMEZONE,
) -> Dict[str, Any]:
    """Fill scheduled_start/scheduled_end in ``update_data`` from raw inputs.

    Precedence:
      1. Direct scheduled_start / scheduled_end datetimes (normalized to the
         system timezone; a missing end is derived from duration_minutes).
      2. Natural-language when/start_time resolved by build_calendar_event_body.

    Never lets the LLM compute final datetimes.
    """
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo(SYSTEM_TIMEZONE)
        timezone = SYSTEM_TIMEZONE

    if update_data.get("scheduled_start") is not None:
        start = update_data["scheduled_start"]
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        else:
            start = start.astimezone(tz)
        end = update_data.get("scheduled_end")
        if end is not None:
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
            else:
                end = end.astimezone(tz)
        elif duration_minutes:
            end = start + timedelta(minutes=duration_minutes)
        update_data["scheduled_start"] = start
        update_data["scheduled_end"] = end
    elif when or start_time:
        body = build_calendar_event_body({
            "summary": "task",
            "when": when,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "timezone": timezone,
        })
        update_data["scheduled_start"] = parse_event_datetime(body["start"]["dateTime"])
        update_data["scheduled_end"] = parse_event_datetime(body["end"]["dateTime"])
    return update_data


def resolve_deadline(deadline_when: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """Resolve a natural-language deadline phrase to a datetime.

    Only the date matters for a deadline; a time in the phrase is honored when
    given, otherwise it resolves to the default event hour on that date.
    """
    if not deadline_when:
        return None
    body = build_calendar_event_body({
        "summary": "deadline",
        "when": deadline_when,
        "timezone": SYSTEM_TIMEZONE,
    })
    return parse_event_datetime(body["start"]["dateTime"])


def sync_task_to_calendar(
    db: Session,
    task,
    *,
    schedule_on_calendar: bool = False,
    when: Optional[str] = None,
    start_time: Optional[str] = None,
    duration_minutes: int = 60,
    timezone: str = SYSTEM_TIMEZONE,
    schedule_changed: bool = False,
    title_changed: bool = False,
) -> None:
    """Create/update the linked Google event for a task.

    - ``schedule_on_calendar=True`` forces a create (if unlinked) or update
      (if already linked).
    - A linked task whose title or schedule changed is updated too.
    - An already-linked task is NEVER re-inserted — it is always updated.

    Failures are stored on the task (calendar_sync_error) and the task row is
    never rolled back. Safe no-op otherwise.
    """
    if not (schedule_on_calendar or (task.google_calendar_event_id and (schedule_changed or title_changed))):
        return
    if task.scheduled_start is not None:
        end_dt = task.scheduled_end or (task.scheduled_start + timedelta(minutes=duration_minutes or 60))
        event_data = build_event_body_from_datetimes(
            task.scheduled_start, end_dt, task.title, task.description, timezone,
        )
    elif schedule_on_calendar and _has_explicit_schedule({
        "when": when,
        "start_time": start_time,
    }):
        event_data = build_calendar_event_body({
            "summary": task.title,
            "description": task.description,
            "when": when,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "timezone": timezone,
        })
    else:
        # A schedule was requested but no date/time was given — never invent a
        # work slot. Without an explicit schedule no calendar event is created.
        if schedule_on_calendar and not task.google_calendar_event_id:
            return
        # Linked task updated without a schedule change: summary-only body is
        # enough for Google's events().update().
        event_data = {"summary": task.title}
        if task.description:
            event_data["description"] = task.description
    tcs_create_or_update_event(db, task, event_data)


# ---------- Task reference resolution (deterministic, server-side) ----------
# When the user says "put the work on the BAJA wiring task on my calendar", the
# planner must NOT guess a task_id and must NOT paraphrase the task reference.
# The server resolves the user's ORIGINAL message verbatim with strict,
# deterministic matching, so an unrelated task (e.g. "Wiring Diagram") is never
# selected merely because it shares a generic token like "wiring", and a
# specific reference ("work on the BAJA wiring") never degrades into the
# ambiguous "the BAJA wiring task".
_TASK_REFERENCE_STOPWORDS = frozenset({
    # Reference context words.
    "the", "a", "an", "task", "todo", "my", "your", "calendar",
    "put", "add", "remove", "link", "unlink", "on", "to", "from", "off",
    "into", "please", "i", "want", "would", "could", "can", "me",
    "this", "that", "it", "these", "those",
    # Task-management action words, so "update the wiring task priority to
    # high" resolves to "wiring" rather than "update ... priority ... high".
    "update", "updating", "delete", "deleting", "complete", "completing",
    "mark", "marked", "set", "change", "changing", "status", "done",
    "deadline", "due", "important", "priority", "high", "low", "medium",
    "critical", "highest", "highestpriority",
    # Scheduling context words — so "…on my calendar tomorrow at 4 PM" does not
    # become part of the task reference when the full message is resolved.
    "at", "tomorrow", "today", "pm", "am", "next", "week", "for",
    "hour", "hours", "minute", "minutes",
})

_TIE_MARGIN = 0.1
_MIN_MATCH_SCORE = 0.5

_AMBIGUOUS_TASK_QUESTIONS = {
    "add": "Which one should I add to the calendar?",
    "remove": "Which one should I remove from the calendar?",
    "update": "Which one did you mean to update?",
    "complete": "Which one should I mark complete?",
    "delete": "Which one should I delete?",
}


def _normalize_task_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _significant_task_tokens(text: str) -> list:
    normalized = _normalize_task_text(text)
    return [
        token for token in normalized.split()
        if token not in _TASK_REFERENCE_STOPWORDS and not token.isdigit()
    ]


def _task_token_match_score(phrase_tokens: list, title_tokens: list) -> float:
    """Score a reference phrase against a task title.

    Coverage (how much of the phrase is present) dominates; precision keeps a
    long, generic title from winning just because it contains the words.
    """
    if not phrase_tokens:
        return 0.0
    phrase_set = set(phrase_tokens)
    title_set = set(title_tokens)
    common = phrase_set & title_set
    if not common:
        return 0.0
    coverage = len(common) / len(phrase_set)
    precision = len(common) / len(title_set) if title_set else 0.0
    return 0.7 * coverage + 0.3 * precision


def _calendar_state_label(task) -> str:
    """Informational calendar status shown in clarification messages.

    Never used to break a title ambiguity — it only helps the user choose.
    """
    return "📅 On calendar" if task.google_calendar_event_id else "Not on calendar"


def resolve_task_for_calendar(
    db: Session,
    task_title: str,
    *,
    task_id: Optional[int] = None,
    op: str = "add",
) -> Dict[str, Any]:
    """Deterministically resolve the existing task the user referred to.

    Resolution priority:
      A. Exact normalized title match.
      B. Strong normalized title match (title equals the reference after
         reference stopwords are removed, e.g. "work on the BAJA wiring task").
      C. Strong token/phrase match (significant-token coverage + precision).
    Weak substring matching is NEVER used.

    Returns:
      {"status": "found", "task": Task, "score": float}        – unambiguous
      {"status": "ambiguous", "message": str, "candidates": [Task]} – tie/near-tie;
          the caller must NOT create/delete any calendar event until resolved
      {"status": "not_found", "message": str}                  – no meaningful match
    """
    phrase_tokens = _significant_task_tokens(task_title)
    normalized_phrase = _normalize_task_text(task_title)
    phrase_signature = " ".join(phrase_tokens)

    if not phrase_tokens:
        return {
            "status": "not_found",
            "had_significant_tokens": False,
            "message": f'I couldn\'t figure out which task you meant by "{task_title}".',
        }

    tasks = db.query(Task).order_by(Task.id.asc()).all()
    if not tasks:
        return {
            "status": "not_found",
            "had_significant_tokens": True,
            "message": "There are no tasks to link yet.",
        }

    scored = []
    for task in tasks:
        normalized_title = _normalize_task_text(task.title)
        title_tokens = _significant_task_tokens(task.title)
        if normalized_title == normalized_phrase:
            score = 1.0
        elif " ".join(title_tokens) == phrase_signature:
            score = 0.98
        else:
            score = _task_token_match_score(phrase_tokens, title_tokens)
        scored.append((score, task))

    scored.sort(key=lambda item: (-item[0], item[1].id))
    top_score = scored[0][0]

    if top_score < _MIN_MATCH_SCORE:
        return {
            "status": "not_found",
            "had_significant_tokens": True,
            "message": f'I couldn\'t find a task matching "{task_title}".',
        }

    tied = [entry for entry in scored if entry[0] >= top_score - _TIE_MARGIN]

    if len(tied) == 1:
        return {"status": "found", "task": tied[0][1], "score": top_score}

    # An explicit task_id naming one of the tied candidates is a legitimate,
    # deterministic tie-breaker (e.g. the planner saw the ID in context).
    if task_id is not None:
        for score, task in tied:
            if task.id == task_id:
                return {"status": "found", "task": task, "score": score}

    candidates = [task for _, task in tied]
    listing = "\n".join(
        f"{index}. {task.title} — {_calendar_state_label(task)}"
        for index, task in enumerate(candidates, 1)
    )
    question = _AMBIGUOUS_TASK_QUESTIONS.get(op, "Which one did you mean?")
    return {
        "status": "ambiguous",
        "message": f'I found multiple tasks matching "{task_title}":\n{listing}\n{question}',
        "candidates": candidates,
    }


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
        "Invalid project category. Use one of: personal, baja, jobprep, college, studyabroad."
    )


def _project_exists(db: Session, project_id: int) -> bool:
    return db.query(Project.id).filter(Project.id == project_id).first() is not None


def _normalize_task_type(value: str | TaskType | None) -> TaskType:
    """Coerce a task_type string (value or name, any case) into a TaskType member."""
    if value is None or value == "":
        return TaskType.WORK
    if isinstance(value, TaskType):
        return value
    normalized = str(value).strip().lower()
    for member in TaskType:
        if normalized in {member.name.lower(), member.value.lower()}:
            return member
    raise ValueError(
        "Invalid task type. Use one of: work, reminder, meeting."
    )


def list_projects(db: Session, req: ListProjectsRequest) -> Dict[str, Any]:
    projects = db.query(Project).filter(Project.status == ProjectStatus.ACTIVE).all()
    return {"data": projects}


def create_project(db: Session, req: CreateProjectRequest) -> Dict[str, Any]:
    category = _normalize_project_category(req.category)
    proj = Project(name=req.name, category=category, status=ProjectStatus.ACTIVE)
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
        deadline = normalize_to_system(
            datetime.fromisoformat(req.deadline.replace("Z", "+00:00"))
        )
    elif getattr(req, "deadline_when", None):
        deadline = resolve_deadline(req.deadline_when)

    try:
        priority = _normalize_task_priority(req.priority)
        task_type = _normalize_task_type(getattr(req, "task_type", None))
    except ValueError as exc:
        return {"data": {"error": str(exc)}}

    if req.project_id is not None and not _project_exists(db, req.project_id):
        return {"data": {"error": f"Project not found: {req.project_id}"}}

    task = Task(
        title=req.title,
        priority=priority,
        task_type=task_type,
        deadline=deadline,
        project_id=req.project_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Task is committed first. Calendar sync is best-effort: on failure the
    # task stays and calendar_sync_error is populated. Never roll back.
    if getattr(req, "schedule_on_calendar", False):
        if _has_explicit_schedule({"when": req.when, "start_time": req.start_time}):
            body = build_calendar_event_body({
                "summary": task.title,
                "description": task.description,
                "when": req.when,
                "start_time": req.start_time,
                "duration_minutes": req.duration_minutes,
                "timezone": "Asia/Kolkata",
            })
            task.scheduled_start = parse_event_datetime(body["start"]["dateTime"])
            task.scheduled_end = parse_event_datetime(body["end"]["dateTime"])
            db.commit()
            sync_task_to_calendar(db, task, schedule_on_calendar=True)
        # No date/time was given — the task is created without a calendar
        # event. A work slot is never invented.
    return {"data": task}


def update_task(db: Session, req: UpdateTaskRequest) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    update_data = req.dict(exclude_unset=True)
    update_data.pop("task_id", None)
    update_data.pop("task_title", None)
    # A planner may emit null/empty for fields it doesn't intend to change.
    # Never apply a blank to enum/status columns or the NOT NULL title — those
    # nulls are spurious, not "clear" intents. deadline / description / the
    # schedule fields keep their explicit-clear semantics.
    for key in ("title", "status", "priority", "task_type"):
        if update_data.get(key) in (None, ""):
            update_data.pop(key, None)
    schedule_on_calendar = update_data.pop("schedule_on_calendar", False)
    when = update_data.pop("when", None)
    start_time = update_data.pop("start_time", None)
    duration_minutes = update_data.pop("duration_minutes", 60)

    # Resolve scheduling fields deterministically (server-side, Asia/Kolkata).
    if update_data.get("scheduled_start") is not None or (when or start_time):
        resolve_task_schedule(
            update_data, when=when, start_time=start_time, duration_minutes=duration_minutes,
        )

    title_changed = "title" in update_data
    schedule_changed = "scheduled_start" in update_data or "scheduled_end" in update_data

    for key, normalizer in (
        ("status", _normalize_task_status),
        ("priority", _normalize_task_priority),
        ("task_type", _normalize_task_type),
    ):
        if key in update_data:
            try:
                update_data[key] = normalizer(update_data[key])
            except ValueError as exc:
                return {"data": {"error": str(exc)}}

    for field, value in update_data.items():
        if field == "deadline" and value is not None:
            # Convert ISO string to datetime; handle Z suffix for UTC
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            task.deadline = normalize_to_system(datetime.fromisoformat(value))
        elif field == "deadline_when":
            task.deadline = resolve_deadline(value)
        elif field == "project_id" and value is not None:
            if not _project_exists(db, value):
                return {"data": {"error": f"Project not found: {value}"}}
            setattr(task, field, value)
        else:
            setattr(task, field, value)
    db.commit()
    db.refresh(task)

    sync_task_to_calendar(
        db, task,
        schedule_on_calendar=bool(schedule_on_calendar),
        when=when, start_time=start_time, duration_minutes=duration_minutes,
        schedule_changed=schedule_changed, title_changed=title_changed,
    )
    return {"data": task}


def complete_task(db: Session, req: CompleteTaskRequest) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    task.status = TaskStatus.DONE
    task.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    return {"data": task}


def _normalize_task_status(value) -> Optional[TaskStatus]:
    """Coerce a status string (name or value, any case) into a TaskStatus member."""
    if value is None or value == "":
        return None
    norm = str(value).strip().lower()
    for member in TaskStatus:
        if norm in {member.name.lower(), member.value.lower()}:
            return member
    raise ValueError(
        "Invalid task status. Use one of: todo, in_progress, blocked, done."
    )


def _normalize_task_priority(value) -> Optional[TaskPriority]:
    """Coerce a priority string (name or value, any case) into a TaskPriority member."""
    if value is None or value == "":
        return None
    norm = str(value).strip().lower()
    for member in TaskPriority:
        if norm in {member.name.lower(), member.value.lower()}:
            return member
    raise ValueError(
        "Invalid task priority. Use one of: low, medium, high, critical."
    )


def bulk_update_tasks(db: Session, req: BulkUpdateTasksRequest) -> Dict[str, Any]:
    """Update many tasks atomically from a scope or explicit id list.

    Safeguards (all validated BEFORE any row is written):
      * An empty task set never mutates anything.
      * A missing/invalid task id aborts the whole operation (no partial update).
      * ``project_id`` scopes the selection and, when combined with explicit
        ``task_ids``, rejects ids that belong to another project.
      * Unknown scope / status / priority values fail fast.

    Bulk updates never touch Google Calendar: they only edit task columns
    (deadline changes do not move the scheduled work-slot event).
    """
    # 1. Validate the updates themselves before touching any row.
    updates = {}
    try:
        if req.status is not None:
            updates["status"] = _normalize_task_status(req.status)
        if req.priority is not None:
            updates["priority"] = _normalize_task_priority(req.priority)
    except ValueError as exc:
        return {"data": {"error": str(exc)}}
    deadline = None
    if req.deadline_when:
        deadline = resolve_deadline(req.deadline_when)
    if not updates and deadline is None:
        return {
            "data": {
                "error": "No changes requested — pass status, priority or deadline_when.",
            }
        }

    # 2. Resolve the target ids from explicit list or scope.
    if req.task_ids:
        ids = list(dict.fromkeys(req.task_ids))
    elif req.scope:
        query = db.query(Task.id)
        if req.project_id is not None:
            query = query.filter(Task.project_id == req.project_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if req.scope == "overdue":
            query = query.filter(Task.deadline < now, Task.status != TaskStatus.DONE)
        elif req.scope == "all_open":
            query = query.filter(Task.status != TaskStatus.DONE)
        elif req.scope == "critical":
            query = query.filter(
                Task.priority == TaskPriority.CRITICAL,
                Task.status != TaskStatus.DONE,
            )
        else:
            return {
                "data": {
                    "error": (
                        f"Unknown scope '{req.scope}'. "
                        "Use 'all_open', 'overdue' or 'critical'."
                    )
                }
            }
        ids = [row[0] for row in query.all()]
    else:
        return {
            "data": {
                "error": "No tasks targeted — pass task_ids or a scope "
                "(e.g. 'all_open').",
            }
        }

    if not ids:
        return {"data": {"error": "No tasks matched the requested scope."}}

    # 3. Load targets and verify EVERY id before mutating (atomic).
    tasks = db.query(Task).filter(Task.id.in_(ids)).all()
    found = {t.id: t for t in tasks}
    missing = [i for i in ids if i not in found]
    if missing:
        return {
            "data": {
                "error": (
                    f"Task(s) not found: {', '.join(str(i) for i in missing)} "
                    "— no changes were made."
                )
            }
        }
    ordered = [found[i] for i in ids]

    if req.project_id is not None:
        foreign = [t.id for t in ordered if t.project_id != req.project_id]
        if foreign:
            return {
                "data": {
                    "error": (
                        f"Task(s) {', '.join(str(i) for i in foreign)} do not belong "
                        f"to project {req.project_id} — no changes were made."
                    )
                }
            }

    # 4. Apply every update, then a single commit (transactional).
    now = datetime.now(timezone.utc)
    for task in ordered:
        if "status" in updates:
            was_done = task.status == TaskStatus.DONE
            task.status = updates["status"]
            if updates["status"] == TaskStatus.DONE and not was_done:
                task.completed_at = now
            elif updates["status"] != TaskStatus.DONE:
                task.completed_at = None
        if "priority" in updates:
            task.priority = updates["priority"]
        if deadline is not None:
            task.deadline = deadline
    db.commit()

    return {
        "data": {
            "updated_count": len(ordered),
            "task_ids": [t.id for t in ordered],
            "applied": {
                "status": updates["status"].name if "status" in updates else None,
                "priority": updates["priority"].name if "priority" in updates else None,
                "deadline": deadline.isoformat() if deadline else None,
            },
        }
    }


def delete_task(db: Session, req: DeleteTaskRequest) -> Dict[str, Any]:
    """Delete a task row. The linked Google event (if any) is removed
    best-effort first — a Google failure never blocks task deletion."""
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    from app.services.task_calendar_sync import delete_event_best_effort
    delete_event_best_effort(task)
    db.delete(task)
    db.commit()
    return {"data": {"deleted_task_id": req.task_id}}


def list_calendar_events(db: Session, req: ListCalendarEventsRequest) -> Dict[str, Any]:
    events = gc_get_upcoming_events(days=7, max_results=20)
    return {"data": events}


def get_today_overview(db: Session, req: GetTodayOverviewRequest) -> Dict[str, Any]:
    """Read-only Today planning overview (never mutates any state).

    Delegates entirely to the deterministic planning service — this wrapper
    exists only so the AI tool dispatcher has a uniform (db, request) shape.
    """
    from app.services.planning_service import get_today_overview as build_today_overview

    return {"data": build_today_overview(db)}


def create_calendar_event(db: Session, req: CreateCalendarEventRequest) -> Dict[str, Any]:
    event = gc_create_calendar_event(req.event_data)
    return {"data": event}


def update_calendar_event(db: Session, req: UpdateCalendarEventRequest) -> Dict[str, Any]:
    updated = gc_update_calendar_event(req.event_id, req.event_data)
    return {"data": updated}


def delete_calendar_event(db: Session, req: DeleteCalendarEventRequest) -> Dict[str, Any]:
    gc_delete_calendar_event(req.event_id)
    return {"data": {"status": "deleted", "event_id": req.event_id}}


def add_task_to_calendar(db: Session, req: AddTaskToCalendarRequest) -> Dict[str, Any]:
    """Link an existing task to Google Calendar (idempotent)."""
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": {"error": f"Task not found: {req.task_id}"}}

    # No date/time given → ask, never invent a work slot. This keeps a request
    # like "put finish the BAJA wiring on my calendar" from creating an event
    # at today 09:00 (already in the past) that vanishes from the calendar list.
    if not _has_explicit_schedule({"when": req.when, "start_time": req.start_time}):
        return {
            "data": {
                "error": (
                    f"I found the task '{task.title}'. "
                    "When should I schedule it on your calendar?"
                ),
                "reply_direct": True,
            }
        }

    body = build_calendar_event_body({
        "summary": task.title,
        "description": task.description,
        "when": req.when,
        "start_time": req.start_time,
        "duration_minutes": req.duration_minutes,
        "timezone": req.timezone,
    })
    task.scheduled_start = parse_event_datetime(body["start"]["dateTime"])
    task.scheduled_end = parse_event_datetime(body["end"]["dateTime"])
    db.commit()
    # Already-linked tasks are updated, never duplicated (see sync helper).
    sync_task_to_calendar(db, task, schedule_on_calendar=True)
    return {"data": task}


def remove_task_from_calendar(db: Session, req: RemoveTaskFromCalendarRequest) -> Dict[str, Any]:
    """Unlink an existing task from Google Calendar; the ECC task is kept."""
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": {"error": f"Task not found: {req.task_id}"}}
    if not task.google_calendar_event_id:
        # Nothing linked: never a fake success and never a Google write.
        return {
            "data": {
                "error": TASK_NOT_LINKED_MESSAGE,
                "reply_direct": True,
            }
        }
    tcs_unlink_event(db, task)
    return {"data": task}

"""Deterministic Today Intelligence for the planning layer.

The overview is computed from backend facts only — never from an AI model.
A future AI planner consumes this structured result; it never calculates
overdue/due-today classification, counts, progress, or calendar availability.

Classification semantics (deliberately calendar-day based, distinct from
/dashboard/stats which uses ``deadline < now`` for its overdue count):
  overdue    = deadline <  start_of_today
  due_today  = start_of_today <= deadline < start_of_tomorrow
A task due earlier today therefore stays under "due today", never "overdue".
Upcoming = [start_of_tomorrow, now + 7 days), matching the existing 7-day
near-term window used by /tasks/upcoming and the AI context builder.

Task collections are mutually exclusive partitions of the open-task set:
overdue > due_today > upcoming > critical. A task appears in exactly one
collection. Focus candidates re-derive from the same facts and can carry
multiple human-readable reasons (e.g. ["overdue", "critical"]).
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core.timeutil import SYSTEM_TIMEZONE, normalize_to_system
from app.models.task import Task, TaskStatus, TaskPriority
from app.models.project import Project, ProjectStatus
from app.schemas.planning import (
    TodayOverview,
    PlanningTasks,
    PlanningTask,
    FocusCandidate,
    PlanningProjects,
    ProjectDeadline,
    WorkloadSummary,
    CalendarOverview,
    CalendarEventInfo,
    FreeWindow,
)
from app.services.google_calendar import (
    get_upcoming_events as gc_get_upcoming_events,
    is_connected as gc_is_connected,
)

_PRIORITY_RANK = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}

_UPCOMING_DAYS = 7
_CALENDAR_EVENTS_LOOKAHEAD_DAYS = 1
_MAX_PROJECT_DEADLINES = 20


def get_today_overview(
    db: Session,
    now: datetime | None = None,
) -> TodayOverview:
    """Build the deterministic Today Overview for the current IST calendar day.

    ``now`` is the reference wall-clock instant (defaults to the real clock).
    It is used by the day-plan approval layer to rebuild the plan at the exact
    moment it was last presented — free windows start at ``now``, so comparing
    two plans generated at different wall-clock times must use the same anchor
    or an unchanged plan would look "changed" every time.
    """
    now = normalize_to_system(now if now is not None else datetime.now(timezone.utc))
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_tomorrow = start_of_today + timedelta(days=1)
    week_end = now + timedelta(days=_UPCOMING_DAYS)

    # Single query loads every open task with its project (joinedload keeps it
    # at one statement regardless of workspace size — no N+1).
    open_tasks = (
        db.query(Task)
        .options(joinedload(Task.project))
        .filter(Task.status != TaskStatus.DONE)
        .order_by(Task.id.asc())
        .all()
    )

    overdue, due_today, upcoming, critical = [], [], [], []
    focus = []
    for t in open_tasks:
        deadline = normalize_to_system(t.deadline)
        if deadline is not None and deadline < start_of_today:
            overdue.append(t)
            focus.append((_focus_tier(t, "overdue"), t, _focus_reasons(t, "overdue")))
        elif deadline is not None and start_of_today <= deadline < start_of_tomorrow:
            due_today.append(t)
            focus.append((_focus_tier(t, "due_today"), t, _focus_reasons(t, "due_today")))
        elif deadline is not None and start_of_tomorrow <= deadline < week_end:
            upcoming.append(t)
            tier = _focus_tier(t, "upcoming")
            if tier is not None:
                focus.append((tier, t, _focus_reasons(t, "upcoming")))
        elif t.priority in (TaskPriority.CRITICAL, TaskPriority.HIGH):
            # Not overdue/due today/upcoming but high-value: surfacing later
            # deadlines (beyond 7 days) or tasks with no deadline at all.
            critical.append(t)

    overdue.sort(key=lambda t: _task_sort_key(t))
    due_today.sort(key=lambda t: _task_sort_key(t))
    upcoming.sort(key=lambda t: _task_sort_key(t))
    critical.sort(key=lambda t: _task_sort_key(t, priority_first=True))

    # Deterministic focus ordering: tier, then earlier deadline, then higher
    # estimated effort, then stable id as tie-breaker.
    focus.sort(
        key=lambda item: (
            item[0],
            normalize_to_system(item[1].deadline),
            -(item[1].estimated_minutes or 0),
            item[1].id,
        )
    )

    focus_candidates = [
        FocusCandidate(
            task_id=t.id,
            title=t.title,
            priority=t.priority,
            deadline=normalize_to_system(t.deadline),
            estimated_minutes=t.estimated_minutes,
            project_id=t.project_id,
            project_name=t.project.name if t.project else None,
            reasons=reasons,
        )
        for _, t, reasons in focus
    ]

    tasks = PlanningTasks(
        overdue=[_planning_task(t) for t in overdue],
        due_today=[_planning_task(t) for t in due_today],
        upcoming=[_planning_task(t) for t in upcoming],
        critical=[_planning_task(t) for t in critical],
    )

    projects = _project_deadlines(db, start_of_today)

    workload = WorkloadSummary(
        total_open_tasks=len(open_tasks),
        overdue_count=len(overdue),
        due_today_count=len(due_today),
        upcoming_count=len(upcoming),
        critical_count=sum(
            1 for t in open_tasks if t.priority == TaskPriority.CRITICAL
        ),
        estimated_minutes_today=sum(
            t.estimated_minutes or 0 for t in due_today
        ),
    )

    calendar = _calendar_overview(now, start_of_today, start_of_tomorrow)

    return TodayOverview(
        generated_at=now,
        timezone=SYSTEM_TIMEZONE,
        tasks=tasks,
        focus_candidates=focus_candidates,
        projects=projects,
        workload=workload,
        calendar=calendar,
    )


def _focus_tier(task: Task, base_reason: str):
    """Return the deterministic focus tier for a candidate, or None.

    Tiers follow the documented precedence:
      0 overdue+critical, 1 overdue+high, 2 overdue,
      3 critical due today, 4 high due today, 5 other due-today,
      6 critical upcoming, 7 high upcoming.
    Upcoming medium/low tasks are not focus candidates (tier None).
    """
    if base_reason == "overdue":
        if task.priority == TaskPriority.CRITICAL:
            return 0
        if task.priority == TaskPriority.HIGH:
            return 1
        return 2
    if base_reason == "due_today":
        if task.priority == TaskPriority.CRITICAL:
            return 3
        if task.priority == TaskPriority.HIGH:
            return 4
        return 5
    # upcoming
    if task.priority == TaskPriority.CRITICAL:
        return 6
    if task.priority == TaskPriority.HIGH:
        return 7
    return None


def _focus_reasons(task: Task, base_reason: str) -> list[str]:
    reasons = [base_reason]
    if task.priority == TaskPriority.CRITICAL:
        reasons.append("critical")
    elif task.priority == TaskPriority.HIGH:
        reasons.append("high")
    return reasons


def _planning_task(t: Task) -> PlanningTask:
    return PlanningTask(
        task_id=t.id,
        title=t.title,
        priority=t.priority,
        status=t.status,
        deadline=normalize_to_system(t.deadline),
        estimated_minutes=t.estimated_minutes,
        project_id=t.project_id,
        project_name=t.project.name if t.project else None,
    )


def _task_sort_key(t: Task, priority_first: bool = False):
    """Deterministic collection ordering (deadline asc, then priority, then id).

    ``priority_first`` surfaces higher-priority items first within the critical
    collection, where deadlines may be absent.
    """
    deadline = normalize_to_system(t.deadline)
    if priority_first:
        return (
            _PRIORITY_RANK[t.priority],
            deadline is None,
            deadline or datetime.max,
            t.id,
        )
    return (deadline is None, deadline or datetime.max, _PRIORITY_RANK[t.priority], t.id)


def _project_deadlines(db: Session, start_of_today: datetime) -> PlanningProjects:
    """Active projects with a deadline today or later, sorted by deadline.

    Progress uses the existing done/total formula. Two aggregate queries keep
    the work constant regardless of project/task counts (no per-project scans).
    """
    projects = (
        db.query(Project)
        .filter(Project.status == ProjectStatus.ACTIVE, Project.deadline >= start_of_today)
        .order_by(Project.deadline.asc(), Project.id.asc())
        .limit(_MAX_PROJECT_DEADLINES)
        .all()
    )

    total_by_project = dict(
        db.query(Task.project_id, func.count(Task.id))
        .filter(Task.project_id.isnot(None))
        .group_by(Task.project_id)
        .all()
    )
    done_by_project = dict(
        db.query(Task.project_id, func.count(Task.id))
        .filter(Task.project_id.isnot(None), Task.status == TaskStatus.DONE)
        .group_by(Task.project_id)
        .all()
    )

    deadlines = []
    for p in projects:
        total = total_by_project.get(p.id, 0)
        done = done_by_project.get(p.id, 0)
        progress = round(done / total, 2) if total else 0.0
        deadlines.append(
            ProjectDeadline(
                project_id=p.id,
                name=p.name,
                deadline=normalize_to_system(p.deadline),
                status=p.status,
                total_tasks=total,
                done_tasks=done,
                progress=progress,
            )
        )
    return PlanningProjects(deadlines=deadlines)


def _calendar_overview(
    now: datetime,
    start_of_today: datetime,
    start_of_tomorrow: datetime,
) -> CalendarOverview:
    """Read-only calendar snapshot: today's events and remaining free windows.

    Reuses google_calendar.get_upcoming_events (never a second reader). A
    disconnected calendar or any fetch failure yields a valid, safe response.
    """
    try:
        if not gc_is_connected():
            return CalendarOverview(connected=False, events=[], free_windows=[])
        raw_events = gc_get_upcoming_events(
            days=_CALENDAR_EVENTS_LOOKAHEAD_DAYS, max_results=20
        )
    except Exception:
        # Cannot verify availability — return an empty, honest overview.
        return CalendarOverview(connected=False, events=[], free_windows=[])

    events = []
    busy = []
    for e in raw_events:
        start = _parse_event_datetime(e.get("start"))
        end = _parse_event_datetime(e.get("end"))
        if start is None or end is None:
            continue
        if not (start < start_of_tomorrow and end > start_of_today):
            continue
        events.append(
            CalendarEventInfo(
                title=e.get("title") or "(no title)",
                start=start,
                end=end,
                all_day=bool(e.get("all_day", False)),
                location=e.get("location"),
            )
        )
        # Clip to the remaining day before subtracting busy time.
        busy_start = max(start, now)
        busy_end = min(end, start_of_tomorrow)
        if busy_end > busy_start:
            busy.append((busy_start, busy_end))

    free_windows = _free_windows(busy, now, start_of_tomorrow)
    return CalendarOverview(connected=True, events=events, free_windows=free_windows)


def _parse_event_datetime(value: str | None):
    """Parse a Google event start/end into an IST-aware datetime.

    All-day events carry date-only values; the end date is exclusive per
    Google's convention, so it maps to 00:00 of that date.
    """
    if not value:
        return None
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(value, "%Y-%m-%d")
        return normalize_to_system(dt)
    except ValueError:
        return None


def _free_windows(
    busy: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> list[FreeWindow]:
    """Free gaps in [window_start, window_end) after busy intervals.

    Overlapping and adjacent (back-to-back) busy intervals are merged first.
    With no busy time the whole remaining window is returned.
    """
    if not busy:
        return [_make_window(window_start, window_end)]

    busy.sort(key=lambda interval: interval[0])
    merged = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    windows = []
    cursor = window_start
    for start, end in merged:
        if start > cursor:
            windows.append(_make_window(cursor, start))
        cursor = max(cursor, end)
    if cursor < window_end:
        windows.append(_make_window(cursor, window_end))
    return windows


def _make_window(start: datetime, end: datetime) -> FreeWindow:
    duration = max(0, int((end - start).total_seconds() // 60))
    return FreeWindow(start=start, end=end, duration_minutes=duration)

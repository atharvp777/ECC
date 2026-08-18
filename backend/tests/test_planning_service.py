"""Deterministic Today planning service tests.

Covers classification, IST boundary behavior, priority handling, focus
candidate ordering, workload totals, project deadlines/progress, calendar
availability/free windows, the empty state, read-only endpoint behavior and
bounded query counts.
"""
import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db, Base
from app.models.task import Task, TaskStatus, TaskPriority
from app.models.project import Project, ProjectStatus, ProjectCategory
from app.services import planning_service

IST = ZoneInfo("Asia/Kolkata")
EVENING_NOW_UTC = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)  # 21:00 IST
MORNING_NOW_UTC = datetime(2026, 8, 18, 3, 30, tzinfo=timezone.utc)  # 09:00 IST


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


def _freeze(monkeypatch, now):
    FakeDatetime = type(
        "FakeDatetime",
        (datetime,),
        {"now": classmethod(lambda cls, tz=None: now)},
    )
    monkeypatch.setattr(planning_service, "datetime", FakeDatetime)


def _add_task(
    db,
    deadline=None,
    priority=TaskPriority.MEDIUM,
    status=TaskStatus.TODO,
    title="Task",
    estimated_minutes=None,
    project_id=None,
):
    task = Task(
        title=title,
        priority=priority,
        status=status,
        deadline=planning_service.normalize_to_system(deadline),
        estimated_minutes=estimated_minutes,
        project_id=project_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _add_project(db, name, deadline=None, status=ProjectStatus.ACTIVE):
    project = Project(
        name=name,
        category=ProjectCategory.PERSONAL,
        status=status,
        deadline=planning_service.normalize_to_system(deadline),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _patch_calendar(monkeypatch, events=None, connected=True):
    monkeypatch.setattr(planning_service, "gc_is_connected", lambda: connected)
    monkeypatch.setattr(
        planning_service,
        "gc_get_upcoming_events",
        lambda days=None, max_results=None: events or [],
    )


# ----------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------

def test_classification_overdue_due_today_upcoming(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)  # 2026-08-18 21:00 IST
    _add_task(db_session, datetime(2026, 8, 17, 23, 59, tzinfo=IST), title="yesterday", priority=TaskPriority.HIGH)
    _add_task(db_session, datetime(2026, 8, 18, 21, 30, tzinfo=IST), title="tonight", priority=TaskPriority.MEDIUM)
    _add_task(db_session, datetime(2026, 8, 19, 9, 0, tzinfo=IST), title="tomorrow", priority=TaskPriority.MEDIUM)

    overview = planning_service.get_today_overview(db_session)

    assert [t.title for t in overview.tasks.overdue] == ["yesterday"]
    assert [t.title for t in overview.tasks.due_today] == ["tonight"]
    assert [t.title for t in overview.tasks.upcoming] == ["tomorrow"]
    assert overview.workload.overdue_count == 1
    assert overview.workload.due_today_count == 1
    assert overview.workload.upcoming_count == 1
    assert overview.workload.total_open_tasks == 3


def test_completed_overdue_task_excluded(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 10, 9, 0, tzinfo=IST), status=TaskStatus.DONE, title="done overdue")

    overview = planning_service.get_today_overview(db_session)

    assert overview.tasks.overdue == []
    assert overview.workload.overdue_count == 0
    assert overview.workload.total_open_tasks == 0


def test_no_deadline_medium_task_not_in_collections_but_counted(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, None, title="no deadline medium")

    overview = planning_service.get_today_overview(db_session)

    assert overview.tasks.overdue == []
    assert overview.tasks.due_today == []
    assert overview.tasks.upcoming == []
    assert overview.tasks.critical == []
    assert overview.focus_candidates == []
    assert overview.workload.total_open_tasks == 1


def test_no_deadline_critical_lands_in_critical_collection(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, None, priority=TaskPriority.CRITICAL, title="no deadline critical")

    overview = planning_service.get_today_overview(db_session)

    assert [t.title for t in overview.tasks.critical] == ["no deadline critical"]
    assert overview.workload.critical_count == 1


def test_critical_due_in_ten_days_lands_in_critical_collection(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 28, 9, 0, tzinfo=IST), priority=TaskPriority.CRITICAL, title="later critical")

    overview = planning_service.get_today_overview(db_session)

    assert overview.tasks.upcoming == []
    assert [t.title for t in overview.tasks.critical] == ["later critical"]


# ----------------------------------------------------------------------
# IST boundaries
# ----------------------------------------------------------------------

def test_boundary_exactly_midnight_ist_is_due_today(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 18, 0, 0, tzinfo=IST), title="midnight exactly")

    overview = planning_service.get_today_overview(db_session)

    assert [t.title for t in overview.tasks.due_today] == ["midnight exactly"]
    assert overview.tasks.overdue == []


def test_boundary_just_before_midnight_ist_is_overdue(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 17, 23, 59, 59, tzinfo=IST), title="just before midnight")

    overview = planning_service.get_today_overview(db_session)

    assert [t.title for t in overview.tasks.overdue] == ["just before midnight"]
    assert overview.tasks.due_today == []


def test_boundary_just_after_midnight_ist_is_due_today(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 18, 0, 0, 1, tzinfo=IST), title="just after midnight")

    overview = planning_service.get_today_overview(db_session)

    assert [t.title for t in overview.tasks.due_today] == ["just after midnight"]
    assert overview.tasks.overdue == []


def test_utc_noon_maps_to_today_ist_date(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    # 12:00 UTC == 17:30 IST on 2026-08-18 → due today.
    _add_task(db_session, datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc), title="utc noon")

    overview = planning_service.get_today_overview(db_session)

    assert [t.title for t in overview.tasks.due_today] == ["utc noon"]
    assert overview.tasks.overdue == []


def test_utc_1900_maps_to_tomorrow_ist_date(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    # 19:00 UTC == 00:30 IST on 2026-08-19 → due tomorrow, not today.
    _add_task(db_session, datetime(2026, 8, 18, 19, 0, tzinfo=timezone.utc), title="utc late")

    overview = planning_service.get_today_overview(db_session)

    assert overview.tasks.due_today == []
    assert [t.title for t in overview.tasks.upcoming] == ["utc late"]


# ----------------------------------------------------------------------
# Priority levels
# ----------------------------------------------------------------------

def test_priority_levels_use_real_enums(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    deadline = datetime(2026, 8, 18, 22, 0, tzinfo=IST)
    for prio in (TaskPriority.CRITICAL, TaskPriority.HIGH, TaskPriority.MEDIUM, TaskPriority.LOW):
        _add_task(db_session, deadline, priority=prio, title=f"task {prio.value}")

    overview = planning_service.get_today_overview(db_session)

    titles = [t.title for t in overview.tasks.due_today]
    assert titles == ["task critical", "task high", "task medium", "task low"]
    assert overview.workload.critical_count == 1


# ----------------------------------------------------------------------
# Multiple reasons / no duplicates
# ----------------------------------------------------------------------

def test_critical_due_today_once_with_both_reasons(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    task = _add_task(
        db_session,
        datetime(2026, 8, 18, 20, 0, tzinfo=IST),
        priority=TaskPriority.CRITICAL,
        title="Complete PCB schematic",
    )

    overview = planning_service.get_today_overview(db_session)

    assert [t.task_id for t in overview.tasks.due_today] == [task.id]
    assert [t.task_id for t in overview.tasks.critical] == []
    assert len(overview.focus_candidates) == 1
    candidate = overview.focus_candidates[0]
    assert candidate.task_id == task.id
    assert candidate.reasons == ["due_today", "critical"]


def test_overdue_critical_reasons(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    task = _add_task(
        db_session,
        datetime(2026, 8, 17, 10, 0, tzinfo=IST),
        priority=TaskPriority.CRITICAL,
        title="late critical",
    )

    overview = planning_service.get_today_overview(db_session)

    candidate = overview.focus_candidates[0]
    assert candidate.task_id == task.id
    assert candidate.reasons == ["overdue", "critical"]


# ----------------------------------------------------------------------
# Focus ordering
# ----------------------------------------------------------------------

def test_focus_candidate_tier_ordering(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 17, 9, 0, tzinfo=IST), priority=TaskPriority.CRITICAL, title="overdue critical")     # tier 0
    _add_task(db_session, datetime(2026, 8, 17, 9, 0, tzinfo=IST), priority=TaskPriority.HIGH, title="overdue high")           # tier 1
    _add_task(db_session, datetime(2026, 8, 17, 9, 0, tzinfo=IST), priority=TaskPriority.MEDIUM, title="overdue medium")       # tier 2
    _add_task(db_session, datetime(2026, 8, 18, 20, 0, tzinfo=IST), priority=TaskPriority.CRITICAL, title="today critical")    # tier 3
    _add_task(db_session, datetime(2026, 8, 18, 20, 0, tzinfo=IST), priority=TaskPriority.HIGH, title="today high")            # tier 4
    _add_task(db_session, datetime(2026, 8, 18, 20, 0, tzinfo=IST), priority=TaskPriority.MEDIUM, title="today medium")        # tier 5
    _add_task(db_session, datetime(2026, 8, 20, 9, 0, tzinfo=IST), priority=TaskPriority.CRITICAL, title="upcoming critical")  # tier 6
    _add_task(db_session, datetime(2026, 8, 20, 9, 0, tzinfo=IST), priority=TaskPriority.HIGH, title="upcoming high")          # tier 7

    overview = planning_service.get_today_overview(db_session)

    titles = [c.title for c in overview.focus_candidates]
    assert titles == [
        "overdue critical",
        "overdue high",
        "overdue medium",
        "today critical",
        "today high",
        "today medium",
        "upcoming critical",
        "upcoming high",
    ]


def test_focus_within_tier_earlier_deadline_first(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 17, 18, 0, tzinfo=IST), title="later overdue")
    _add_task(db_session, datetime(2026, 8, 17, 9, 0, tzinfo=IST), title="earlier overdue")

    overview = planning_service.get_today_overview(db_session)

    assert [c.title for c in overview.focus_candidates] == ["earlier overdue", "later overdue"]


def test_focus_within_tier_higher_effort_first(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    deadline = datetime(2026, 8, 17, 9, 0, tzinfo=IST)
    _add_task(db_session, deadline, title="effort 30", estimated_minutes=30)
    _add_task(db_session, deadline, title="effort 60", estimated_minutes=60)
    _add_task(db_session, deadline, title="effort none")

    overview = planning_service.get_today_overview(db_session)

    assert [c.title for c in overview.focus_candidates] == ["effort 60", "effort 30", "effort none"]


# ----------------------------------------------------------------------
# Estimated workload
# ----------------------------------------------------------------------

def test_estimated_minutes_today_sums_due_today_only(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 18, 21, 0, tzinfo=IST), title="30", estimated_minutes=30)
    _add_task(db_session, datetime(2026, 8, 18, 21, 0, tzinfo=IST), title="null", estimated_minutes=None)
    _add_task(db_session, datetime(2026, 8, 18, 21, 0, tzinfo=IST), title="zero", estimated_minutes=0)
    _add_task(db_session, datetime(2026, 8, 18, 21, 0, tzinfo=IST), title="sixty", estimated_minutes=60)
    _add_task(db_session, datetime(2026, 8, 17, 9, 0, tzinfo=IST), title="overdue effort", estimated_minutes=999)
    _add_task(db_session, datetime(2026, 8, 19, 9, 0, tzinfo=IST), title="upcoming effort", estimated_minutes=999)
    _add_task(db_session, datetime(2026, 8, 18, 21, 0, tzinfo=IST), title="done effort", estimated_minutes=500, status=TaskStatus.DONE)

    overview = planning_service.get_today_overview(db_session)

    assert overview.workload.estimated_minutes_today == 90
    assert overview.workload.due_today_count == 4


# ----------------------------------------------------------------------
# Project deadlines & progress
# ----------------------------------------------------------------------

def test_active_project_with_deadline_and_progress(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    project = _add_project(db_session, "BAJA HV", deadline=datetime(2026, 8, 20, tzinfo=IST))
    _add_task(db_session, None, project_id=project.id, status=TaskStatus.DONE)
    _add_task(db_session, None, project_id=project.id, status=TaskStatus.DONE)
    _add_task(db_session, None, project_id=project.id, status=TaskStatus.TODO)

    overview = planning_service.get_today_overview(db_session)

    assert len(overview.projects.deadlines) == 1
    entry = overview.projects.deadlines[0]
    assert entry.project_id == project.id
    assert entry.name == "BAJA HV"
    assert entry.total_tasks == 3
    assert entry.done_tasks == 2
    assert entry.progress == pytest.approx(0.67)


def test_project_without_deadline_excluded(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_project(db_session, "No deadline")

    overview = planning_service.get_today_overview(db_session)

    assert overview.projects.deadlines == []


def test_completed_and_archived_projects_excluded(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    deadline = datetime(2026, 8, 25, tzinfo=IST)
    _add_project(db_session, "Finished", deadline=deadline, status=ProjectStatus.COMPLETED)
    _add_project(db_session, "Archived", deadline=deadline, status=ProjectStatus.ARCHIVED)
    _add_project(db_session, "Active", deadline=deadline, status=ProjectStatus.ACTIVE)

    overview = planning_service.get_today_overview(db_session)

    assert [p.name for p in overview.projects.deadlines] == ["Active"]


def test_project_progress_zero_when_no_tasks(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    project = _add_project(db_session, "Empty", deadline=datetime(2026, 8, 20, tzinfo=IST))

    overview = planning_service.get_today_overview(db_session)

    entry = overview.projects.deadlines[0]
    assert entry.project_id == project.id
    assert entry.total_tasks == 0
    assert entry.done_tasks == 0
    assert entry.progress == 0.0


def test_project_overdue_deadline_excluded(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _add_project(db_session, "Past deadline", deadline=datetime(2026, 8, 1, tzinfo=IST))

    overview = planning_service.get_today_overview(db_session)

    assert overview.projects.deadlines == []


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------

def test_calendar_disconnected(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=False)

    overview = planning_service.get_today_overview(db_session)

    assert overview.calendar.connected is False
    assert overview.calendar.events == []
    assert overview.calendar.free_windows == []


def test_calendar_connected_no_events_full_day_free(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)  # 09:00 IST
    _patch_calendar(monkeypatch, events=[])

    overview = planning_service.get_today_overview(db_session)

    assert overview.calendar.connected is True
    assert overview.calendar.events == []
    assert len(overview.calendar.free_windows) == 1
    window = overview.calendar.free_windows[0]
    assert window.start.hour == 9 and window.start.minute == 0
    assert window.end.hour == 0 and window.end.minute == 0
    assert window.duration_minutes == 15 * 60


def test_calendar_one_event(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "Meeting", "start": "2026-08-18T10:00:00+05:30", "end": "2026-08-18T11:00:00+05:30", "all_day": False},
    ])

    overview = planning_service.get_today_overview(db_session)

    assert len(overview.calendar.events) == 1
    assert overview.calendar.events[0].title == "Meeting"
    windows = [(w.duration_minutes, w.start.hour, w.end.hour) for w in overview.calendar.free_windows]
    assert windows == [(60, 9, 10), (13 * 60, 11, 0)]


def test_calendar_multiple_events(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "A", "start": "2026-08-18T10:00:00+05:30", "end": "2026-08-18T11:00:00+05:30", "all_day": False},
        {"title": "B", "start": "2026-08-18T13:00:00+05:30", "end": "2026-08-18T14:00:00+05:30", "all_day": False},
    ])

    overview = planning_service.get_today_overview(db_session)

    windows = [w.duration_minutes for w in overview.calendar.free_windows]
    assert windows == [60, 120, 10 * 60]


def test_calendar_overlapping_events_merged(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "A", "start": "2026-08-18T10:00:00+05:30", "end": "2026-08-18T12:00:00+05:30", "all_day": False},
        {"title": "B", "start": "2026-08-18T11:00:00+05:30", "end": "2026-08-18T13:00:00+05:30", "all_day": False},
    ])

    overview = planning_service.get_today_overview(db_session)

    windows = [w.duration_minutes for w in overview.calendar.free_windows]
    assert windows == [60, 11 * 60]


def test_calendar_adjacent_events_merged(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "A", "start": "2026-08-18T10:00:00+05:30", "end": "2026-08-18T11:00:00+05:30", "all_day": False},
        {"title": "B", "start": "2026-08-18T11:00:00+05:30", "end": "2026-08-18T12:00:00+05:30", "all_day": False},
    ])

    overview = planning_service.get_today_overview(db_session)

    windows = [w.duration_minutes for w in overview.calendar.free_windows]
    assert windows == [60, 12 * 60]


def test_calendar_all_day_event_blocks_whole_day(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "Outing", "start": "2026-08-18", "end": "2026-08-19", "all_day": True},
    ])

    overview = planning_service.get_today_overview(db_session)

    assert len(overview.calendar.events) == 1
    assert overview.calendar.events[0].all_day is True
    assert overview.calendar.free_windows == []


def test_calendar_event_outside_today_excluded(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "Tomorrow", "start": "2026-08-19T10:00:00+05:30", "end": "2026-08-19T11:00:00+05:30", "all_day": False},
    ])

    overview = planning_service.get_today_overview(db_session)

    assert overview.calendar.events == []
    assert len(overview.calendar.free_windows) == 1
    assert overview.calendar.free_windows[0].duration_minutes == 15 * 60


def test_calendar_event_crossing_midnight_clipped(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, events=[
        {"title": "Late", "start": "2026-08-18T23:00:00+05:30", "end": "2026-08-19T01:00:00+05:30", "all_day": False},
    ])

    overview = planning_service.get_today_overview(db_session)

    assert len(overview.calendar.events) == 1
    windows = [w.duration_minutes for w in overview.calendar.free_windows]
    assert windows == [14 * 60]  # 09:00 → 23:00


def test_calendar_fetch_failure_is_safe(db_session, monkeypatch):
    _freeze(monkeypatch, MORNING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=True)

    def boom(days=None, max_results=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(planning_service, "gc_get_upcoming_events", boom)

    overview = planning_service.get_today_overview(db_session)

    assert overview.calendar.connected is False
    assert overview.calendar.events == []
    assert overview.calendar.free_windows == []


# ----------------------------------------------------------------------
# Empty state
# ----------------------------------------------------------------------

def test_empty_state(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=False)

    overview = planning_service.get_today_overview(db_session)

    assert overview.tasks.overdue == []
    assert overview.tasks.due_today == []
    assert overview.tasks.upcoming == []
    assert overview.tasks.critical == []
    assert overview.focus_candidates == []
    assert overview.projects.deadlines == []
    assert overview.workload.total_open_tasks == 0
    assert overview.workload.overdue_count == 0
    assert overview.workload.due_today_count == 0
    assert overview.workload.upcoming_count == 0
    assert overview.workload.critical_count == 0
    assert overview.workload.estimated_minutes_today == 0
    assert overview.calendar.connected is False
    assert overview.calendar.free_windows == []
    assert overview.timezone == "Asia/Kolkata"


# ----------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------

def test_endpoint_today_read_only(client, db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=False)
    _add_task(db_session, datetime(2026, 8, 18, 22, 0, tzinfo=IST), priority=TaskPriority.CRITICAL, title="endpoint task")
    before = (db_session.query(Task).count(), db_session.query(Project).count())

    response = client.get("/planning/today")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "generated_at", "timezone", "tasks", "focus_candidates",
        "projects", "workload", "calendar",
    }
    assert payload["timezone"] == "Asia/Kolkata"
    assert [t["title"] for t in payload["tasks"]["due_today"]] == ["endpoint task"]
    assert payload["focus_candidates"][0]["reasons"] == ["due_today", "critical"]
    assert payload["calendar"]["connected"] is False
    assert payload["workload"]["estimated_minutes_today"] == 0

    after = (db_session.query(Task).count(), db_session.query(Project).count())
    assert before == after


def test_endpoint_empty_state_returns_valid_overview(client, db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=False)

    response = client.get("/planning/today")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workload"]["total_open_tasks"] == 0
    assert payload["tasks"]["overdue"] == []
    assert payload["projects"]["deadlines"] == []
    assert payload["calendar"]["free_windows"] == []


# ----------------------------------------------------------------------
# Performance: bounded query count
# ----------------------------------------------------------------------

def test_planning_query_count_is_bounded(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=False)
    now = datetime.now()

    projects = []
    for i in range(25):
        p = _add_project(db_session, f"Project {i}", deadline=datetime(2026, 8, 20, tzinfo=IST))
        projects.append(p)
    for i, p in enumerate(projects):
        for j in range(5):
            deadline = now - timedelta(days=1) if j == 0 else now + timedelta(days=j + 1)
            status = "done" if j == 2 else "todo"
            _add_task(
                db_session,
                deadline=deadline,
                status=status,
                priority=TaskPriority.HIGH if j % 2 else TaskPriority.MEDIUM,
                project_id=p.id,
                title=f"task {i}-{j}",
            )

    counter = {"n": 0}

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _count(*args, **kwargs):
        counter["n"] += 1

    overview = planning_service.get_today_overview(db_session)

    assert counter["n"] <= 8
    assert overview.workload.total_open_tasks == 100


def test_planning_query_count_bounded_on_empty_db(db_session, monkeypatch):
    _freeze(monkeypatch, EVENING_NOW_UTC)
    _patch_calendar(monkeypatch, connected=False)

    counter = {"n": 0}

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _count(*args, **kwargs):
        counter["n"] += 1

    planning_service.get_today_overview(db_session)

    assert counter["n"] <= 8

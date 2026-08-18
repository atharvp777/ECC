"""Date/time handling regression tests.

The system operates in Asia/Kolkata. Deadlines and schedule boundaries must be
normalized to that zone so SQLite's lexicographic datetime comparisons stay
chronologically correct and "today" windows line up with the user's calendar.
"""
import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db, Base
from app.core.timeutil import SYSTEM_TIMEZONE, normalize_to_system
from app.models.task import Task, TaskStatus, TaskPriority
from app.schemas.task import TaskCreate
from app.schemas.project import ProjectCreate
from app.services import ai_service
from app.routers import tasks as tasks_router
from app.routers import dashboard as dashboard_router

IST = ZoneInfo("Asia/Kolkata")
FIXED_NOW_UTC = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)  # 21:00 IST


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


def _freeze(monkeypatch, module, now):
    FakeDatetime = type(
        "FakeDatetime",
        (datetime,),
        {"now": classmethod(lambda cls, tz=None: now)},
    )
    monkeypatch.setattr(module, "datetime", FakeDatetime)


def _add_task(db, deadline, status=TaskStatus.TODO, title="Task"):
    task = Task(title=title, priority=TaskPriority.MEDIUM, status=status, deadline=deadline)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ----------------------------------------------------------------------
# normalize_to_system
# ----------------------------------------------------------------------

def test_normalize_naive_assumed_system_tz():
    result = normalize_to_system(datetime(2026, 8, 18, 9, 0))
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(hours=5, minutes=30)


def test_normalize_utc_converted_to_ist():
    result = normalize_to_system(datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc))
    assert result.hour == 23 and result.minute == 30
    assert result.utcoffset() == timedelta(hours=5, minutes=30)


def test_normalize_none():
    assert normalize_to_system(None) is None


# ----------------------------------------------------------------------
# Schema-level deadline normalization
# ----------------------------------------------------------------------

def test_taskcreate_deadline_normalized_to_ist():
    task = TaskCreate(
        title="T",
        deadline=datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc),
    )
    assert task.deadline.utcoffset() == timedelta(hours=5, minutes=30)
    assert task.deadline.hour == 23


def test_projectcreate_date_only_deadline_assumed_ist():
    project = ProjectCreate(name="P", deadline="2026-08-20")
    assert project.deadline.utcoffset() == timedelta(hours=5, minutes=30)
    assert project.deadline.hour == 0


# ----------------------------------------------------------------------
# Endpoint boundary windows (system timezone, not UTC)
# ----------------------------------------------------------------------

def test_tasks_today_excludes_tomorrow_early_morning(client, monkeypatch, db_session):
    # Frozen at 21:00 IST. A task due 02:00 IST tomorrow must NOT be "today"
    # (the old UTC end-of-day window wrongly included it until 05:29 IST).
    _freeze(monkeypatch, tasks_router, FIXED_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 19, 2, 0, tzinfo=IST), title="tomorrow 2am")

    response = client.get("/tasks/today")
    assert response.status_code == 200
    assert response.json() == []


def test_tasks_today_includes_due_later_today(client, monkeypatch, db_session):
    _freeze(monkeypatch, tasks_router, FIXED_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 18, 23, 0, tzinfo=IST), title="due tonight")

    response = client.get("/tasks/today")
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["due tonight"]


def test_tasks_upcoming_uses_system_time_window(client, monkeypatch, db_session):
    _freeze(monkeypatch, tasks_router, FIXED_NOW_UTC)
    _add_task(db_session, datetime(2026, 8, 21, 9, 0, tzinfo=IST), title="in 3 days")
    _add_task(db_session, datetime(2026, 8, 18, 20, 0, tzinfo=IST), title="earlier today")

    response = client.get("/tasks/upcoming")
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["in 3 days"]


def test_dashboard_due_today_uses_system_boundaries(client, monkeypatch, db_session):
    _freeze(monkeypatch, dashboard_router, FIXED_NOW_UTC)
    # Due at 02:00 IST tomorrow == not due today; due 23:00 IST today == due today.
    _add_task(db_session, datetime(2026, 8, 19, 2, 0, tzinfo=IST), title="tomorrow 2am")
    _add_task(db_session, datetime(2026, 8, 18, 23, 0, tzinfo=IST), title="due tonight")

    stats = client.get("/dashboard/stats").json()
    assert stats["due_today"] == 1
    assert stats["overdue_tasks"] == 0


def test_dashboard_deadline_normalized_through_api(client, db_session):
    # A UTC deadline via the API is stored as IST wall-clock.
    response = client.post(
        "/tasks/",
        json={
            "title": "utc noon",
            "priority": "medium",
            "deadline": "2026-08-18T12:00:00+00:00",
        },
    )
    assert response.status_code == 201
    task = db_session.query(Task).filter(Task.title == "utc noon").first()
    assert task.deadline.hour == 17 and task.deadline.minute == 30


# ----------------------------------------------------------------------
# AI context: overdue days computed from the real instant
# ----------------------------------------------------------------------

def test_build_context_overdue_days_uses_real_instant(monkeypatch, db_session):
    _freeze(monkeypatch, ai_service, FIXED_NOW_UTC)
    # Due 20:30 IST (== 15:00 UTC), frozen now 21:00 IST (== 15:30 UTC):
    # 30 minutes overdue → "0d overdue". A naive replace(tzinfo=utc) misuse
    # would compute -1d instead.
    _add_task(db_session, datetime(2026, 8, 18, 20, 30, tzinfo=IST), title="half an hour late")

    ctx = ai_service._build_context(db_session)
    assert "0d overdue" in ctx
    assert "-1d overdue" not in ctx
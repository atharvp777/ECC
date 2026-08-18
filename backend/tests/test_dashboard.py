import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db, Base
from app.models.task import Task, TaskStatus, TaskPriority
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client, db
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _add_task(db, deadline, status=TaskStatus.TODO):
    task = Task(
        title="Task",
        priority=TaskPriority.MEDIUM,
        status=status,
        deadline=deadline,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _freeze_now(monkeypatch):
    fixed_now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    FakeDatetime = type(
        "FakeDatetime",
        (datetime,),
        {"now": classmethod(lambda cls, tz=None: fixed_now)},
    )
    monkeypatch.setattr("app.routers.dashboard.datetime", FakeDatetime)
    return fixed_now


def test_due_today_only_counts_today(client, monkeypatch):
    test_client, db = client
    _freeze_now(monkeypatch)

    _add_task(db, datetime(2026, 1, 15, 20, 30, tzinfo=IST))    # due today -> counted
    _add_task(db, datetime(2026, 1, 13, 15, 30, tzinfo=IST))    # overdue -> NOT due today
    _add_task(db, datetime(2026, 1, 16, 14, 30, tzinfo=IST))    # tomorrow -> NOT due today
    _add_task(db, None)                                         # no deadline -> NOT due today
    _add_task(db, datetime(2026, 1, 15, 19, 30, tzinfo=IST), status=TaskStatus.DONE)  # done today -> NOT due today

    response = test_client.get("/dashboard/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["due_today"] == 1
    assert stats["overdue_tasks"] == 1


def test_due_today_empty_when_nothing_due_today(client, monkeypatch):
    test_client, db = client
    _freeze_now(monkeypatch)

    _add_task(db, datetime(2026, 1, 18, 14, 30, tzinfo=IST))    # in 3 days
    _add_task(db, datetime(2026, 1, 10, 14, 30, tzinfo=IST))    # 5 days ago

    response = test_client.get("/dashboard/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["due_today"] == 0
    assert stats["overdue_tasks"] == 1


def test_due_today_excludes_done_overdue_and_tomorrow(client, monkeypatch):
    test_client, db = client
    _freeze_now(monkeypatch)

    _add_task(db, datetime(2026, 1, 15, 19, 30, tzinfo=IST), status=TaskStatus.DONE)
    _add_task(db, datetime(2026, 1, 16, 14, 30, tzinfo=IST))    # tomorrow
    _add_task(db, datetime(2026, 1, 14, 14, 30, tzinfo=IST))    # overdue

    response = test_client.get("/dashboard/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["due_today"] == 0
    assert stats["overdue_tasks"] == 1
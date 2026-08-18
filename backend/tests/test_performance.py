"""Performance regression guards.

Context building runs on every chat message, so its SQL cost must stay
constant even as the workspace grows. These tests assert the query count is
bounded regardless of how many projects/tasks/documents exist (no N+1 lazy
loads on the hot path).
"""
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.project import Project
from app.models.task import Task, TaskPriority
from app.models.note import Note
from app.services.ai_service import _build_context


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session, engine


def test_build_context_query_count_is_bounded(db_session):
    Session, engine = db_session
    now = datetime.now()

    projs = []
    for i in range(25):
        projs.append(
            Project(
                name=f"Project {i}",
                category="personal",
                status="active",
                description="desc " + ("x" * 50),
            )
        )
    s0 = Session()
    s0.add_all(projs)
    s0.commit()
    for p in projs:
        s0.refresh(p)

    for i, p in enumerate(projs):
        s = Session()
        for j in range(5):
            deadline = now - timedelta(days=1) if j == 0 else now + timedelta(days=j)
            status = "done" if j == 2 else "todo"
            s.add(
                Task(
                    title=f"task {i}-{j}",
                    priority="medium" if j % 2 else "high",
                    status=status,
                    project_id=p.id,
                    deadline=deadline,
                )
            )
        s.add(Note(title=f"note {i}"))
        s.commit()
        s.close()

    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*args, **kwargs):
        counter["n"] += 1

    context = _build_context(Session())
    # projects + selectinload tasks + selectinload documents + overdue +
    # upcoming + critical + notes ≈ 7 statements. Anything near the lazy N+1
    # count (tens of extra loads) fails this guard.
    assert counter["n"] <= 12
    assert "Project 0" in context
    assert "task 0-0" in context


def test_build_context_projects_without_tasks_still_bounded(db_session):
    Session, engine = db_session
    for i in range(10):
        Session().add(Project(name=f"Empty {i}", category="personal", status="active"))
    Session().commit()

    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*args, **kwargs):
        counter["n"] += 1

    _build_context(Session())
    assert counter["n"] <= 12
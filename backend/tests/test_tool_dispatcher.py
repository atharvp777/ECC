"""Tool dispatcher edge-case tests.

Covers the defensive branches in ``execute_tool`` and ``_resolve_project_name``:
unknown tools, malformed references, missing required arguments, project-name
resolution failures, and calendar-event write guards. No Google calls run — the
guards reject or short-circuit before any network access.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Project, Task
from app.services.tool_dispatcher import execute_tool


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _project(db, name="Proj"):
    p = Project(name=name, category="personal", status="ACTIVE")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _task(db, title):
    t = Task(title=title, priority="MEDIUM", status="TODO")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ----------------------------------------------------------------------
# execute_tool — structural guards
# ----------------------------------------------------------------------

def test_execute_unknown_tool_returns_error(db_session):
    result = execute_tool("does_not_exist", {}, db_session)
    assert "error" in result["data"]
    assert "Unknown tool" in result["data"]["error"]


def test_execute_wraps_exception_in_error_data(db_session):
    # A request-model validation error (e.g. an invalid priority enum) must
    # surface as a data error, never an uncaught exception.
    result = execute_tool("create_task", {"title": "x", "priority": "bogus"}, db_session)
    assert "error" in result["data"]


def test_execute_calendar_tool_requires_event_id(db_session):
    result = execute_tool("update_calendar_event", {"event_id": ""}, db_session)
    assert "error" in result["data"]
    assert "event_id" in result["data"]["error"]

    result = execute_tool("delete_calendar_event", {}, db_session)
    assert "error" in result["data"]
    assert "event_id" in result["data"]["error"]


def test_execute_calendar_tool_rejects_non_event_id(db_session):
    # "task 3" looks like a task title, not a Google event id — must be rejected
    # before any Google call.
    result = execute_tool("update_calendar_event", {"event_id": "task 3"}, db_session)
    assert "error" in result["data"]
    assert "not a known Google Calendar event id" in result["data"]["error"]


def test_execute_task_mutation_requires_reference(db_session):
    for tool in ("update_task", "complete_task", "delete_task"):
        result = execute_tool(tool, {}, db_session)
        assert "error" in result["data"]
        assert "requires a task_id or a task_title" in result["data"]["error"]


def test_execute_calendar_task_tools_require_reference(db_session):
    for tool in ("add_task_to_calendar", "remove_task_from_calendar"):
        result = execute_tool(tool, {}, db_session)
        assert "error" in result["data"]
        assert "requires a task_title or a task_id" in result["data"]["error"]


def test_execute_task_title_must_be_string(db_session):
    t = _task(db_session, "Design")
    result = execute_tool("complete_task", {"task_title": 123, "task_id": t.id}, db_session)
    assert "error" in result["data"]


# ----------------------------------------------------------------------
# _resolve_project_name — via create_task project_name argument
# ----------------------------------------------------------------------

def test_create_task_with_unknown_project_name(db_session):
    result = execute_tool("create_task", {"title": "x", "project_name": "Nope"}, db_session)
    assert "error" in result["data"]
    assert "Project not found" in result["data"]["error"]


def test_create_task_with_ambiguous_project_name(db_session):
    _project(db_session, "Team A")
    _project(db_session, "team a")
    # Upper-case reference: no exact match, but two case-insensitive matches.
    result = execute_tool("create_task", {"title": "x", "project_name": "TEAM A"}, db_session)
    assert "error" in result["data"]
    assert "Ambiguous" in result["data"]["error"]


def test_create_task_with_non_string_project_name(db_session):
    result = execute_tool("create_task", {"title": "x", "project_name": 123}, db_session)
    assert "error" in result["data"]


def test_create_task_resolves_project_name_by_exact_match(db_session):
    p = _project(db_session, "Baja")
    result = execute_tool(
        "create_task",
        {"title": "Work", "project_name": "Baja"},
        db_session,
    )
    assert "data" in result and isinstance(result["data"], Task)
    created = db_session.query(Task).filter_by(title="Work").first()
    assert created is not None
    assert created.project_id == p.id


def test_bulk_update_tasks_unknown_project_name(db_session):
    result = execute_tool(
        "bulk_update_tasks",
        {"scope": "all_open", "project_name": "Missing", "status": "done"},
        db_session,
    )
    assert "error" in result["data"]
    assert "Project not found" in result["data"]["error"]
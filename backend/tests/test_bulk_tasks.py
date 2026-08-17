"""Bulk task operations and task deletion tests.

``bulk_update_tasks`` must be atomic and scoped: an invalid id, a cross-project
id, an unknown scope/status or an empty target set aborts the WHOLE operation
before any row is mutated. ``delete_task`` deletes a task (linked Google event
is removed best-effort) and only the backend's success result may be reported
by the AI as "Deleted".
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Project, Task, TaskStatus, TaskPriority
from app.services.tools import (
    bulk_update_tasks,
    delete_task,
    complete_task,
    BulkUpdateTasksRequest,
    DeleteTaskRequest,
)
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


def _task(db, title, *, project=None, deadline=None, priority="MEDIUM", status="TODO"):
    t = Task(
        title=title,
        priority=priority,
        status=status,
        deadline=deadline,
        project_id=project.id if project else None,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _bulk(db, **kwargs):
    return bulk_update_tasks(db, BulkUpdateTasksRequest(**kwargs))


# ----------------------------------------------------------------------
# bulk_update_tasks — targeting
# ----------------------------------------------------------------------
def test_bulk_complete_by_ids(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)
    t2 = _task(db_session, "B", project=proj)
    t3 = _task(db_session, "C", project=proj)

    result = _bulk(db_session, task_ids=[t1.id, t3.id], status="done")

    assert result["data"]["updated_count"] == 2
    db_session.refresh(t1)
    db_session.refresh(t2)
    db_session.refresh(t3)
    assert t1.status == TaskStatus.DONE and t1.completed_at is not None
    assert t2.status == TaskStatus.TODO
    assert t3.status == TaskStatus.DONE


def test_bulk_all_open_scoped_to_project(db_session):
    proj_a = _project(db_session, "A")
    proj_b = _project(db_session, "B")
    a1 = _task(db_session, "a1", project=proj_a)
    a2 = _task(db_session, "a2", project=proj_a, status="DONE")
    b1 = _task(db_session, "b1", project=proj_b)

    result = _bulk(db_session, scope="all_open", project_id=proj_a.id, status="done")

    assert result["data"]["updated_count"] == 1
    db_session.refresh(a1)
    db_session.refresh(b1)
    assert a1.status == TaskStatus.DONE
    assert b1.status == TaskStatus.TODO


def test_bulk_overdue_scope(db_session):
    proj = _project(db_session)
    past = _task(db_session, "past", project=proj, deadline=datetime(2020, 1, 1))
    future = _task(db_session, "future", project=proj, deadline=datetime(2030, 1, 1))

    result = _bulk(db_session, scope="overdue", status="done")

    assert result["data"]["updated_count"] == 1
    db_session.refresh(past)
    db_session.refresh(future)
    assert past.status == TaskStatus.DONE
    assert future.status == TaskStatus.TODO


def test_bulk_critical_scope(db_session):
    proj = _project(db_session)
    crit = _task(db_session, "crit", project=proj, priority="CRITICAL")
    _task(db_session, "med", project=proj, priority="MEDIUM")

    result = _bulk(db_session, scope="critical", status="done")

    assert result["data"]["updated_count"] == 1
    db_session.refresh(crit)
    assert crit.status == TaskStatus.DONE


# ----------------------------------------------------------------------
# bulk_update_tasks — safeguards
# ----------------------------------------------------------------------
def test_bulk_empty_scope_errors_without_mutation(db_session):
    result = _bulk(db_session, scope="overdue", status="done")
    assert "error" in result["data"]
    assert "No tasks matched" in result["data"]["error"]


def test_bulk_no_targets_errors(db_session):
    result = _bulk(db_session, status="done")
    assert "error" in result["data"]
    assert "No tasks targeted" in result["data"]["error"]


def test_bulk_no_changes_requested_errors(db_session):
    proj = _project(db_session)
    _task(db_session, "A", project=proj)
    result = _bulk(db_session, scope="all_open")
    assert "error" in result["data"]
    assert "No changes requested" in result["data"]["error"]


def test_bulk_missing_id_aborts_whole_operation(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)

    result = _bulk(db_session, task_ids=[t1.id, 99999], status="done")

    assert "error" in result["data"]
    assert "99999" in result["data"]["error"]
    db_session.refresh(t1)
    assert t1.status == TaskStatus.TODO  # nothing was mutated


def test_bulk_cross_project_id_rejected(db_session):
    proj_a = _project(db_session, "A")
    proj_b = _project(db_session, "B")
    b1 = _task(db_session, "b1", project=proj_b)

    result = _bulk(db_session, task_ids=[b1.id], project_id=proj_a.id, status="done")

    assert "error" in result["data"]
    assert "do not belong" in result["data"]["error"]
    db_session.refresh(b1)
    assert b1.status == TaskStatus.TODO


def test_bulk_invalid_status_errors(db_session):
    proj = _project(db_session)
    _task(db_session, "A", project=proj)
    result = _bulk(db_session, scope="all_open", status="shipped")
    assert "error" in result["data"]
    assert "Invalid task status" in result["data"]["error"]


def test_bulk_invalid_scope_errors(db_session):
    result = _bulk(db_session, scope="everything", status="done")
    assert "error" in result["data"]
    assert "Unknown scope" in result["data"]["error"]


def test_bulk_duplicate_ids_deduplicated(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)
    result = _bulk(db_session, task_ids=[t1.id, t1.id], status="done")
    assert result["data"]["updated_count"] == 1


def test_bulk_priority_and_deadline_update(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)

    result = _bulk(
        db_session,
        task_ids=[t1.id],
        priority="high",
        deadline_when="2026-09-01",
    )

    assert result["data"]["updated_count"] == 1
    assert result["data"]["applied"]["priority"] == "HIGH"
    assert result["data"]["applied"]["deadline"] is not None
    db_session.refresh(t1)
    assert t1.priority == TaskPriority.HIGH
    assert t1.deadline is not None


def test_bulk_status_away_from_done_clears_completed_at(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj, status="DONE")

    _bulk(db_session, task_ids=[t1.id], status="todo")

    db_session.refresh(t1)
    assert t1.status == TaskStatus.TODO
    assert t1.completed_at is None


# ----------------------------------------------------------------------
# execute_tool integration
# ----------------------------------------------------------------------
def test_bulk_via_dispatcher_resolves_project_name(db_session):
    proj = _project(db_session, "In-SEM")
    _task(db_session, "a", project=proj)
    _task(db_session, "b", project=proj)

    result = execute_tool(
        "bulk_update_tasks",
        {"scope": "all_open", "project_name": "in-sem", "status": "done"},
        db_session,
    )

    assert result["data"]["updated_count"] == 2


def test_bulk_via_dispatcher_unknown_project(db_session):
    result = execute_tool(
        "bulk_update_tasks",
        {"scope": "all_open", "project_name": "DoesNotExist", "status": "done"},
        db_session,
    )
    assert "error" in result["data"]
    assert "Project not found" in result["data"]["error"]


# ----------------------------------------------------------------------
# delete_task
# ----------------------------------------------------------------------
def test_delete_task_removes_row(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)
    t2 = _task(db_session, "B", project=proj)

    result = delete_task(db_session, DeleteTaskRequest(task_id=t1.id))

    assert result["data"]["deleted_task_id"] == t1.id
    assert db_session.query(Task).filter(Task.id == t1.id).first() is None
    assert db_session.query(Task).filter(Task.id == t2.id).first() is not None


def test_delete_task_missing_returns_none(db_session):
    result = delete_task(db_session, DeleteTaskRequest(task_id=999))
    assert result["data"] is None


def test_delete_task_via_dispatcher(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)
    result = execute_tool("delete_task", {"task_id": t1.id}, db_session)
    assert result["data"]["deleted_task_id"] == t1.id
    assert db_session.query(Task).filter(Task.id == t1.id).first() is None


# ----------------------------------------------------------------------
# complete_task sets completed_at
# ----------------------------------------------------------------------
def test_complete_task_sets_completed_at(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "A", project=proj)
    complete_task(db_session, type("Req", (), {"task_id": t1.id})())
    db_session.refresh(t1)
    assert t1.status == TaskStatus.DONE
    assert t1.completed_at is not None


# ----------------------------------------------------------------------
# chat_with_ai renderers (honest replies)
# ----------------------------------------------------------------------
def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


def test_chat_bulk_renderer(db_session):
    from app.services.ai_service import chat_with_ai

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps({
                "tool": "bulk_update_tasks",
                "args": {"scope": "all_open", "project_name": "Proj", "status": "done"},
            })
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {
                "data": {
                    "updated_count": 2,
                    "task_ids": [1, 2],
                    "applied": {"status": "DONE", "priority": None, "deadline": None},
                }
            }
            reply = chat_with_ai(
                [{"role": "user", "content": "Mark all my tasks in Proj done"}],
                db_session,
            )

    assert "Updated 2 tasks" in reply
    assert "marked done" in reply


def test_chat_bulk_renderer_single_task(db_session):
    from app.services.ai_service import chat_with_ai

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps({
                "tool": "bulk_update_tasks",
                "args": {"scope": "overdue", "status": "done"},
            })
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {
                "data": {
                    "updated_count": 1,
                    "task_ids": [1],
                    "applied": {"status": "DONE", "priority": None, "deadline": None},
                }
            }
            reply = chat_with_ai(
                [{"role": "user", "content": "Complete all overdue tasks"}],
                db_session,
            )

    assert "Updated 1 task" in reply


def test_chat_bulk_error_is_reported_honestly(db_session):
    from app.services.ai_service import chat_with_ai

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps({
                "tool": "bulk_update_tasks",
                "args": {"scope": "overdue", "status": "done"},
            })
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": {"error": "No tasks matched the requested scope."}}
            reply = chat_with_ai(
                [{"role": "user", "content": "Complete all overdue tasks"}],
                db_session,
            )

    assert "No tasks matched" in reply


def test_chat_delete_renderer(db_session):
    from app.services.ai_service import chat_with_ai

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps({"tool": "delete_task", "args": {"task_id": 1}})
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": {"deleted_task_id": 1}}
            reply = chat_with_ai(
                [{"role": "user", "content": "Delete task 1"}],
                db_session,
            )

    assert "Deleted task 1" in reply


def test_chat_delete_missing_is_not_fake_success(db_session):
    from app.services.ai_service import chat_with_ai

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps({"tool": "delete_task", "args": {"task_id": 999}})
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": None}
            reply = chat_with_ai(
                [{"role": "user", "content": "Delete task 999"}],
                db_session,
            )

    assert "no result was returned" in reply
    assert "Deleted" not in reply


# ----------------------------------------------------------------------
# Title-based task resolution (deterministic, never invented ids)
# ----------------------------------------------------------------------
def test_complete_task_resolves_by_title(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "Wiring Diagram", project=proj)
    _task(db_session, "Other", project=proj)

    result = execute_tool(
        "complete_task",
        {"task_title": "wiring diagram"},
        db_session,
        user_message="mark the wiring diagram task done",
    )

    assert result["data"].id == t1.id
    db_session.refresh(t1)
    assert t1.status == TaskStatus.DONE
    assert "Other" in [t.title for t in db_session.query(Task).all()]


def test_update_task_resolves_by_title(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "Wiring Diagram", project=proj)

    result = execute_tool(
        "update_task",
        {"task_title": "wiring diagram", "priority": "high"},
        db_session,
        user_message="update the wiring diagram task priority to high",
    )

    db_session.refresh(t1)
    assert t1.priority == TaskPriority.HIGH
    assert result["data"].id == t1.id


def test_delete_task_resolves_by_title(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "Wiring Diagram", project=proj)
    _task(db_session, "Keep Me", project=proj)

    result = execute_tool(
        "delete_task",
        {"task_title": "wiring diagram"},
        db_session,
        user_message="delete the wiring diagram task",
    )

    assert result["data"]["deleted_task_id"] == t1.id
    assert db_session.query(Task).filter(Task.id == t1.id).first() is None
    assert db_session.query(Task).filter(Task.title == "Keep Me").first() is not None


def test_complete_task_ambiguous_title_clarifies_no_mutation(db_session):
    proj = _project(db_session)
    _task(db_session, "Wiring", project=proj)
    _task(db_session, "Wiring", project=proj)  # exact duplicate title → tie

    result = execute_tool(
        "complete_task",
        {"task_title": "wiring"},
        db_session,
        user_message="mark the wiring task done",
    )

    assert "reply_direct" in result["data"]
    assert "Which one" in result["data"]["error"]
    assert all(t.status != TaskStatus.DONE for t in db_session.query(Task).all())


def test_complete_task_title_not_found_no_mutation(db_session):
    proj = _project(db_session)
    _task(db_session, "Wiring Diagram", project=proj)

    result = execute_tool(
        "complete_task",
        {"task_title": "suspension"},
        db_session,
        user_message="mark the suspension task done",
    )

    assert "reply_direct" in result["data"]
    assert "couldn't find a task matching" in result["data"]["error"]
    assert all(t.status != TaskStatus.DONE for t in db_session.query(Task).all())


def test_complete_task_bare_id_reference_uses_task_id(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "Wiring Diagram", project=proj)

    result = execute_tool(
        "complete_task",
        {"task_id": t1.id},
        db_session,
        user_message="mark task 5 done",  # no significant title tokens
    )

    assert result["data"].id == t1.id
    db_session.refresh(t1)
    assert t1.status == TaskStatus.DONE


def test_update_task_direct_id_still_works(db_session):
    proj = _project(db_session)
    t1 = _task(db_session, "Wiring Diagram", project=proj)

    result = execute_tool(
        "update_task",
        {"task_id": t1.id, "title": "New name"},
        db_session,
    )

    db_session.refresh(t1)
    assert t1.title == "New name"


def test_update_task_missing_id_no_reference_errors(db_session):
    result = execute_tool("update_task", {"title": "X"}, db_session)
    assert "error" in result["data"]
    assert "requires a task_id" in result["data"]["error"]


def test_chat_complete_ambiguous_returns_clarification(db_session):
    from app.services.ai_service import chat_with_ai

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps({"tool": "complete_task", "args": {"task_title": "wiring"}})
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {
                "data": {
                    "error": 'I found multiple tasks matching "wiring":\n1. Wiring\n2. Wiring Diagram\nWhich one should I mark complete?',
                    "reply_direct": True,
                    "candidates": [1, 2],
                }
            }
            reply = chat_with_ai(
                [{"role": "user", "content": "mark the wiring task done"}],
                db_session,
            )

    assert "Which one" in reply
    assert "failed" not in reply


# ----------------------------------------------------------------------
# renderer error branches — honest, never fake success
# ----------------------------------------------------------------------

def test_render_task_updated_reports_calendar_sync_failure():
    from types import SimpleNamespace
    from app.services.ai_service import _render_task_updated, _safe_sync_reason

    data = SimpleNamespace(id=7, calendar_sync_error="Google API 403")
    assert "Updated task 7." in _render_task_updated(data)
    assert "Calendar sync failed" in _render_task_updated(data)

    # A non-write-access error is sanitized into a generic reason.
    assert _safe_sync_reason("connection reset") == "Google Calendar is unavailable right now"
    assert _safe_sync_reason("") == "unknown Google Calendar error"
    assert _safe_sync_reason("Insufficient Permission") == "Insufficient Permission"


def test_render_task_calendar_linked_sync_failure():
    from types import SimpleNamespace
    from app.services.ai_service import _render_task_calendar_linked

    data = SimpleNamespace(title="Wind test", google_calendar_event_id=None, calendar_sync_error="Google API 403")
    assert "couldn't add" in _render_task_calendar_linked(data)
    assert "Google Calendar is unavailable right now" in _render_task_calendar_linked(data)


def test_render_task_calendar_removed_sync_failure():
    from types import SimpleNamespace
    from app.services.ai_service import _render_task_calendar_removed

    data = SimpleNamespace(title="Wind test", google_calendar_event_id="evt-1", calendar_sync_error="Google API 403")
    assert "couldn't remove" in _render_task_calendar_removed(data)
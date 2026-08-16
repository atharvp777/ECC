"""Task ↔ Google Calendar integration tests.

Covers the full sync flow with the Google Calendar API mocked — no real
calendar events are ever created. Cases:

  A. Scheduling a new task creates the task AND its calendar event.
  B. A deadline-only task is NOT put on the calendar.
  C. A calendar write failure keeps the task and records calendar_sync_error
     (never a fake success).
  D. No duplicate events: an already-linked task is updated, never re-inserted.
  E. add_task_to_calendar links an existing task.
  F. remove_task_from_calendar unlinks a task (task kept).
  G. Task deletion attempts Google deletion but never blocks on failure.
  H. Updating a linked task's schedule updates the Google event (no dup).
  I. Completing a task keeps its linked event (no auto-delete).
  J. Completed tasks never lose their link on status-only updates.
  K. Planner routing: schedule→create_task(+calendar), deadline→create_task,
     link/remove→add/remove_task_from_calendar.
  L. The chat guard allows create_task WITH schedule_on_calendar but refuses
     mis-routed calendar writes to other task tools.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services import google_calendar
from app.services.ai_service import (
    plan_tool_call,
    chat_with_ai,
)
from app.services.tools import (
    CreateTaskRequest,
    UpdateTaskRequest,
    AddTaskToCalendarRequest,
    RemoveTaskFromCalendarRequest,
    create_task as create_task_tool,
    update_task as update_task_tool,
    add_task_to_calendar as add_task_to_calendar_tool,
    remove_task_from_calendar as remove_task_from_calendar_tool,
    complete_task as complete_task_tool,
    CompleteTaskRequest,
)
from app.services.task_calendar_sync import delete_event_best_effort
from app.models import Task
from app.models.task import TaskStatus


# ----------------------------------------------------------------------
# Helpers / fixtures
# ----------------------------------------------------------------------
def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
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
    from app.core.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _linked_task(db_session, title="Wiring"):
    task = Task(title=title, priority="MEDIUM", google_calendar_event_id="evt_existing")
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


# ----------------------------------------------------------------------
# A. Schedule creates task + event (mocked Google)
# ----------------------------------------------------------------------
def test_schedule_task_creates_task_and_calendar_event(db_session):
    created = {"id": "evt_sched_1", "summary": "Wiring", "status": "confirmed"}
    with patch.object(google_calendar, "create_calendar_event", return_value=created) as mock_create:
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Wiring",
            priority="HIGH",
            when="tomorrow",
            start_time="16:00",
            duration_minutes=60,
            schedule_on_calendar=True,
        ))

    task = result["data"]
    assert task.google_calendar_event_id == "evt_sched_1"
    assert task.calendar_sync_error is None
    assert task.scheduled_start is not None
    assert task.scheduled_end is not None
    assert task.scheduled_end - task.scheduled_start == timedelta(minutes=60)

    # Event body carried the resolved schedule (offset-aware, Asia/Kolkata).
    insert_call = mock_create.call_args.args[0]
    assert insert_call["summary"] == "Wiring"
    assert insert_call["start"]["timeZone"] == "Asia/Kolkata"
    assert insert_call["start"]["dateTime"].endswith("+05:30")


# ----------------------------------------------------------------------
# B. Deadline-only task is NOT put on the calendar
# ----------------------------------------------------------------------
def test_deadline_task_does_not_touch_calendar(db_session):
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Finish report",
            priority="MEDIUM",
            deadline_when="Friday",
        ))

    task = result["data"]
    assert task.deadline is not None
    assert task.google_calendar_event_id is None
    assert task.scheduled_start is None
    mock_create.assert_not_called()


# ----------------------------------------------------------------------
# C. Calendar failure keeps task + records sync error (no fake success)
# ----------------------------------------------------------------------
def test_calendar_failure_keeps_task_and_records_error(db_session):
    with patch.object(
        google_calendar, "create_calendar_event", side_effect=RuntimeError("network down")
    ):
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Wiring",
            priority="MEDIUM",
            when="tomorrow",
            schedule_on_calendar=True,
        ))

    task = result["data"]
    # The task must exist and never be rolled back.
    assert task.id is not None
    assert db_session.query(Task).filter(Task.id == task.id).first() is not None
    assert task.google_calendar_event_id is None
    assert task.calendar_sync_error == "network down"


# ----------------------------------------------------------------------
# D. No duplicate events
# ----------------------------------------------------------------------
def test_update_linked_task_updates_event_not_insert(db_session):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_existing"}
        result = update_task_tool(db_session, UpdateTaskRequest(
            task_id=task.id,
            title="Wiring v2",
        ))

    updated = result["data"]
    assert updated.google_calendar_event_id == "evt_existing"
    mock_update.assert_called_once()
    assert mock_update.call_args.args[0] == "evt_existing"
    mock_create.assert_not_called()


# ----------------------------------------------------------------------
# E. Link existing task
# ----------------------------------------------------------------------
def test_add_task_to_calendar_links_existing_task(db_session):
    task = Task(title="Wiring", priority="MEDIUM")
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_new"}) as mock_create:
        result = add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(
            task_id=task.id,
            when="tomorrow",
            start_time="15:00",
        ))

    assert result["data"].google_calendar_event_id == "evt_new"
    assert result["data"].scheduled_start is not None
    # The Google event carried the resolved offset-aware time.
    insert_call = mock_create.call_args.args[0]
    assert insert_call["start"]["dateTime"].endswith("+05:30")


def test_add_task_to_calendar_twice_is_idempotent(db_session):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_existing"}
        add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(
            task_id=task.id, when="tomorrow",
        ))
        add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(
            task_id=task.id, when="tomorrow",
        ))

    # Only updates — the event is never duplicated.
    assert mock_update.call_count == 2
    mock_create.assert_not_called()
    assert task.google_calendar_event_id == "evt_existing"


# ----------------------------------------------------------------------
# F. Unlink task (task kept)
# ----------------------------------------------------------------------
def test_remove_task_from_calendar_unlinks_but_keeps_task(db_session):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
        result = remove_task_from_calendar_tool(db_session, RemoveTaskFromCalendarRequest(task_id=task.id))

    mock_delete.assert_called_once_with("evt_existing")
    assert result["data"].google_calendar_event_id is None
    assert result["data"].scheduled_start is None
    assert result["data"].calendar_sync_error is None
    # The ECC task still exists.
    assert db_session.query(Task).filter(Task.id == task.id).first() is not None


# ----------------------------------------------------------------------
# G. Task deletion never blocks on Google failure
# ----------------------------------------------------------------------
def test_delete_event_best_effort_suppresses_google_errors(db_session):
    task = _linked_task(db_session)
    with patch.object(
        google_calendar, "delete_calendar_event", side_effect=RuntimeError("offline")
    ):
        delete_event_best_effort(task)  # must not raise
    assert task.google_calendar_event_id == "evt_existing"


def test_router_delete_task_removes_task_even_when_google_fails(db_session, client):
    task = Task(title="Wiring", priority="MEDIUM", google_calendar_event_id="evt_del")
    db_session.add(task)
    db_session.commit()

    with patch.object(
        google_calendar, "delete_calendar_event", side_effect=RuntimeError("offline")
    ):
        resp = client.delete(f"/tasks/{task.id}")

    assert resp.status_code == 204
    assert client.get(f"/tasks/{task.id}").status_code == 404


# ----------------------------------------------------------------------
# H. Updating a linked task's schedule updates the Google event
# ----------------------------------------------------------------------
def test_update_linked_task_schedule_updates_google_event(db_session):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_existing"}
        update_task_tool(db_session, UpdateTaskRequest(
            task_id=task.id,
            when="tomorrow",
            start_time="14:00",
            duration_minutes=90,
        ))

    mock_update.assert_called_once()
    event_data = mock_update.call_args.args[1]
    assert event_data["start"]["timeZone"] == "Asia/Kolkata"
    assert event_data["start"]["dateTime"].endswith("+05:30")
    mock_create.assert_not_called()
    assert task.google_calendar_event_id == "evt_existing"


# ----------------------------------------------------------------------
# I & J. Completing / status-only updates keep the linked event
# ----------------------------------------------------------------------
def test_complete_task_keeps_linked_event(db_session):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "delete_calendar_event") as mock_delete, \
         patch.object(google_calendar, "update_calendar_event") as mock_update:
        complete_task_tool(db_session, CompleteTaskRequest(task_id=task.id))

    assert task.status == TaskStatus.DONE
    assert task.google_calendar_event_id == "evt_existing"
    mock_delete.assert_not_called()
    mock_update.assert_not_called()


def test_status_only_update_does_not_touch_google(db_session):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "delete_calendar_event") as mock_delete:
        update_task_tool(db_session, UpdateTaskRequest(task_id=task.id, status="IN_PROGRESS"))

    assert task.google_calendar_event_id == "evt_existing"
    mock_update.assert_not_called()
    mock_delete.assert_not_called()


# ----------------------------------------------------------------------
# K. Planner routing
# ----------------------------------------------------------------------
def test_planner_routes_scheduled_task_to_create_task():
    payload = {
        "tool": "create_task",
        "args": {
            "title": "Wiring",
            "priority": "MEDIUM",
            "when": "tomorrow",
            "start_time": "16:00",
            "duration_minutes": 60,
            "schedule_on_calendar": True,
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call("work on the wiring tomorrow at 4 PM", "ctx")

    assert result["tool"] == "create_task"
    assert result["args"]["schedule_on_calendar"] is True


def test_planner_routes_deadline_task_without_calendar():
    payload = {
        "tool": "create_task",
        "args": {
            "title": "Finish report",
            "priority": "MEDIUM",
            "deadline_when": "Friday",
            "schedule_on_calendar": False,
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call("create a task to finish the report by Friday", "ctx")

    assert result["tool"] == "create_task"
    assert result["args"]["schedule_on_calendar"] is False


def test_planner_routes_link_existing_task_to_add_tool():
    payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_id": 7, "when": "tomorrow", "start_time": "15:00", "timezone": "Asia/Kolkata"},
    }
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call("put task 7 on my calendar tomorrow at 3pm", "ctx")

    assert result["tool"] == "add_task_to_calendar"
    assert result["args"]["task_id"] == 7


def test_planner_routes_remove_existing_task_to_remove_tool():
    payload = {"tool": "remove_task_from_calendar", "args": {"task_id": 7}}
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call("remove task 7 from my calendar", "ctx")

    assert result["tool"] == "remove_task_from_calendar"


# ----------------------------------------------------------------------
# L. Chat guard
# ----------------------------------------------------------------------
def test_chat_refuses_misrouted_calendar_write_to_update_task(db_session):
    planner_payload = {
        "tool": "update_task",
        "args": {"task_id": 1, "schedule_on_calendar": True},
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            reply = chat_with_ai(
                [{"role": "user", "content": "put my wiring task on my calendar tomorrow at 4pm"}],
                db_session,
            )

    mock_execute.assert_not_called()
    assert "no calendar event" in reply.lower()


def test_chat_allows_create_task_with_schedule_on_calendar(db_session):
    planner_payload = {
        "tool": "create_task",
        "args": {
            "title": "Wiring",
            "priority": "MEDIUM",
            "when": "tomorrow",
            "start_time": "16:00",
            "schedule_on_calendar": True,
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            task = Task(
                title="Wiring",
                priority="MEDIUM",
                google_calendar_event_id="evt_ok",
            )
            db_session.add(task)
            db_session.commit()
            db_session.refresh(task)
            mock_execute.return_value = {"data": task}
            reply = chat_with_ai(
                [{"role": "user", "content": "schedule the wiring task tomorrow at 4pm on my calendar"}],
                db_session,
            )

    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[0] == "create_task"
    assert "Created task" in reply
    assert "added it to your Google Calendar" in reply


def test_chat_reports_partial_success_honestly(db_session):
    planner_payload = {
        "tool": "create_task",
        "args": {
            "title": "Wiring",
            "priority": "MEDIUM",
            "when": "tomorrow",
            "schedule_on_calendar": True,
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            task = Task(
                title="Wiring",
                priority="MEDIUM",
                calendar_sync_error="Google API unreachable",
            )
            db_session.add(task)
            db_session.commit()
            db_session.refresh(task)
            mock_execute.return_value = {"data": task}
            reply = chat_with_ai(
                [{"role": "user", "content": "schedule the wiring task tomorrow at 4pm"}],
                db_session,
            )

    assert "Created task" in reply
    assert "couldn't add it to your Google Calendar" in reply
    # No fake success.
    assert "added it to your Google Calendar" not in reply


# ----------------------------------------------------------------------
# Router: calendar link/unlink endpoints
# ----------------------------------------------------------------------
def test_router_post_calendar_links_task(db_session, client):
    task = Task(title="Wiring", priority="MEDIUM")
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_route"}):
        resp = client.post(
            f"/tasks/{task.id}/calendar",
            json={"when": "tomorrow", "start_time": "15:00", "duration_minutes": 60},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["google_calendar_event_id"] == "evt_route"
    assert body["scheduled_start"] is not None


def test_router_post_calendar_on_linked_task_updates_not_duplicates(db_session, client):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_existing"}
        resp = client.post(
            f"/tasks/{task.id}/calendar",
            json={"when": "tomorrow", "start_time": "10:00"},
        )

    assert resp.status_code == 200
    assert resp.json()["google_calendar_event_id"] == "evt_existing"
    mock_update.assert_called_once()
    mock_create.assert_not_called()


def test_router_delete_calendar_unlinks_but_keeps_task(db_session, client):
    task = _linked_task(db_session)
    with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
        resp = client.delete(f"/tasks/{task.id}/calendar")

    assert resp.status_code == 200
    body = resp.json()
    assert body["google_calendar_event_id"] is None
    mock_delete.assert_called_once_with("evt_existing")
    # The task still exists.
    assert client.get(f"/tasks/{task.id}").status_code == 200

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
from app.services.tools import (
    resolve_task_for_calendar,
)
from app.services.tool_dispatcher import execute_tool
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
    task = Task(title=title, priority="medium", google_calendar_event_id="evt_existing")
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def _qa_scheduled_task(db_session, linked=True):
    task = Task(
        title="QA scheduled task",
        priority="medium",
        google_calendar_event_id="evt_qa_scheduled" if linked else None,
    )
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
            priority="high",
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
            priority="medium",
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
            priority="medium",
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
    task = Task(title="Wiring", priority="medium")
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
    # The Orbit task still exists.
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
    task = Task(title="Wiring", priority="medium", google_calendar_event_id="evt_del")
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
                priority="medium",
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
                priority="medium",
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
    task = Task(title="Wiring", priority="medium")
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


# ----------------------------------------------------------------------
# M. Deterministic task-reference resolution (the "Wiring Diagram" bug)
# ----------------------------------------------------------------------
# Database used by every regression below:
#   - finish the BAJA wiring
#   - work on the BAJA wiring   (correctly linked from the scheduled-task test)
#   - Wiring Diagram            (INCORRECTLY got linked before the fix)
#   - Final Test
def _seed_wiring_tasks(db_session):
    t1 = Task(title="finish the BAJA wiring", priority="medium")
    t2 = Task(title="work on the BAJA wiring", priority="medium")
    t3 = Task(title="Wiring Diagram", priority="low")
    t4 = Task(title="Final Test", priority="medium")
    for t in (t1, t2, t3, t4):
        db_session.add(t)
    db_session.commit()
    for t in (t1, t2, t3, t4):
        db_session.refresh(t)
    return t1, t2, t3, t4


def _clarify(planner_payload, user_message, db_session):
    with patch("app.services.ai_service.Groq") as mock_groq, \
         patch("app.services.ai_service.is_connected", return_value=False):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client
        return chat_with_ai([{"role": "user", "content": user_message}], db_session)


# ---- Resolver: exact task ID selected is correct (requirement 9) ----
def test_resolver_work_on_baja_wiring_returns_exact_id(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "the work on the BAJA wiring task")
    assert result["status"] == "found"
    assert result["task"].id == t2.id


def test_resolver_finish_baja_wiring_returns_exact_id(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "the finish the BAJA wiring task")
    assert result["status"] == "found"
    assert result["task"].id == t1.id


def test_resolver_exact_title_picks_wiring_diagram(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "Wiring Diagram")
    assert result["status"] == "found"
    assert result["task"].id == t3.id


# ---- Resolver: BAJA wiring is genuinely ambiguous, never silently chosen ----
def test_resolver_baja_wiring_is_ambiguous_between_the_two_baja_tasks(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "the BAJA wiring task")
    assert result["status"] == "ambiguous"
    assert [t.id for t in result["candidates"]] == [t1.id, t2.id]
    # "Wiring Diagram" must not be a selected candidate here.
    assert t3.id not in [t.id for t in result["candidates"]]


def test_resolver_wiring_alone_is_ambiguous_never_wiring_diagram(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "the wiring task")
    # Never a silent single selection of the first "wiring" task.
    assert result["status"] == "ambiguous"
    assert t3.id in [t.id for t in result["candidates"]]


def test_resolver_ambiguous_uses_explicit_task_id_as_tiebreaker(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "the BAJA wiring task", task_id=t2.id)
    assert result["status"] == "found"
    assert result["task"].id == t2.id


def test_resolver_not_found_is_honest(db_session):
    _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "aircraft fuel pump")
    assert result["status"] == "not_found"


# ---- Dispatcher: task_title → deterministic task, or clarification ----
def test_dispatcher_resolves_task_title_for_add(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_work"}) as mock_create:
        result = execute_tool(
            "add_task_to_calendar",
            {"task_title": "the work on the BAJA wiring task", "when": "tomorrow"},
            db_session,
        )

    task = result["data"]
    assert task.id == t2.id
    assert task.google_calendar_event_id == "evt_work"
    assert mock_create.call_args.args[0]["summary"] == "work on the BAJA wiring"


def test_dispatcher_ambiguous_returns_clarification_no_write(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        result = execute_tool(
            "add_task_to_calendar",
            {"task_title": "the BAJA wiring task"},
            db_session,
        )

    data = result["data"]
    assert data["reply_direct"] is True
    assert "multiple tasks" in data["error"]
    assert "finish the BAJA wiring" in data["error"]
    assert "work on the BAJA wiring" in data["error"]
    assert "Which one should I add to the calendar?" in data["error"]
    mock_create.assert_not_called()


# ---- Chat: full flow with the real dispatcher, mocked Google ----
def test_chat_ambiguous_baja_wiring_returns_clarification_no_event(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        reply = _clarify(planner_payload, "Put the BAJA wiring task on my calendar.", db_session)

    assert "multiple tasks" in reply
    assert "finish the BAJA wiring" in reply
    assert "work on the BAJA wiring" in reply
    assert "Which one should I add to the calendar?" in reply
    # No calendar event may be created while the task is ambiguous.
    mock_create.assert_not_called()
    assert t3.google_calendar_event_id is None


def test_chat_put_wiring_diagram_links_the_correct_task(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "Wiring Diagram", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_wd"}) as mock_create:
        reply = _clarify(planner_payload, "Put Wiring Diagram on my calendar.", db_session)

    assert 'Added "Wiring Diagram" to your Google Calendar.' in reply
    mock_create.assert_called_once()
    assert t3.google_calendar_event_id == "evt_wd"
    # The BAJA tasks are untouched.
    assert t1.google_calendar_event_id is None
    assert t2.google_calendar_event_id is None


def test_chat_put_work_task_links_the_correct_task(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the work on the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_work"}) as mock_create:
        reply = _clarify(planner_payload, "Put the work on the BAJA wiring task on my calendar.", db_session)

    assert 'Added "work on the BAJA wiring" to your Google Calendar.' in reply
    mock_create.assert_called_once()
    assert t2.google_calendar_event_id == "evt_work"
    assert t1.google_calendar_event_id is None


def test_chat_planner_misroutes_existing_task_to_calendar_event_reroutes(db_session):
    # The planner sometimes returns the raw create_calendar_event tool with a
    # summary that matches an existing task. The server must re-route through
    # the task-calendar tool (idempotent link/update), never create a
    # duplicate event for the task.
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {"summary": "Wiring Diagram", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_wd"}) as mock_create:
        reply = _clarify(planner_payload, "Put Wiring Diagram on my calendar tomorrow.", db_session)

    assert 'Added "Wiring Diagram" to your Google Calendar.' in reply
    mock_create.assert_called_once()
    assert t3.google_calendar_event_id == "evt_wd"
    assert t1.google_calendar_event_id is None
    assert t2.google_calendar_event_id is None


def test_chat_planner_misroutes_update_event_id_to_task_title_reroutes(db_session):
    # The planner sometimes fabricates an event_id from a TASK TITLE for
    # update_calendar_event ("Move <task> to ..."). The server must re-route
    # through add_task_to_calendar (which updates the task's real linked
    # event) instead of failing on an unknown event id — never create a
    # duplicate or claim a fake event update.
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t2.google_calendar_event_id = "evt_existing"
    db_session.commit()
    planner_payload = {
        "tool": "update_calendar_event",
        "args": {"event_id": "work on the BAJA wiring", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_existing"}) as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        reply = _clarify(planner_payload, "Move work on the BAJA wiring to tomorrow.", db_session)

    assert 'Moved "work on the BAJA wiring" to your Google Calendar.' in reply
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    assert t2.google_calendar_event_id == "evt_existing"
    assert t1.google_calendar_event_id is None


def test_chat_planner_misroutes_delete_event_id_to_task_title_reroutes(db_session):
    # Same defense for delete_calendar_event: an event_id fabricated from a
    # task title must be re-routed to remove_task_from_calendar, which deletes
    # the task's real linked event (never a fabricated event).
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t2.google_calendar_event_id = "evt_existing"
    db_session.commit()
    planner_payload = {
        "tool": "delete_calendar_event",
        "args": {"event_id": "work on the BAJA wiring"},
    }
    with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
        reply = _clarify(planner_payload, "Remove work on the BAJA wiring from my calendar.", db_session)

    assert 'Removed "work on the BAJA wiring" from your Google Calendar.' in reply
    mock_delete.assert_called_once_with("evt_existing")
    assert t2.google_calendar_event_id is None
    assert t1.google_calendar_event_id is None


def test_chat_remove_resolves_and_unlinks_correct_task(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t1.google_calendar_event_id = "evt_finish"
    db_session.commit()
    planner_payload = {
        "tool": "remove_task_from_calendar",
        "args": {"task_title": "the finish the BAJA wiring task"},
    }
    with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
        reply = _clarify(planner_payload, "Put the finish the BAJA wiring task off my calendar.", db_session)

    assert 'Removed "finish the BAJA wiring" from your Google Calendar.' in reply
    mock_delete.assert_called_once_with("evt_finish")
    assert t1.google_calendar_event_id is None
    assert t2.google_calendar_event_id is None


def test_chat_already_linked_task_updates_not_duplicates(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t2.google_calendar_event_id = "evt_existing"
    db_session.commit()
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the work on the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_existing"}
        reply = _clarify(planner_payload, "Put the work on the BAJA wiring task on my calendar.", db_session)

    assert 'Added "work on the BAJA wiring" to your Google Calendar.' in reply
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    assert t2.google_calendar_event_id == "evt_existing"


def test_chat_wiring_alone_never_selects_wiring_diagram(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        reply = _clarify(planner_payload, "Put the wiring task on my calendar.", db_session)

    # It must be ambiguous — "Wiring Diagram" must not win merely for "wiring".
    assert "multiple tasks" in reply
    mock_create.assert_not_called()
    assert t3.google_calendar_event_id is None
    assert t2.google_calendar_event_id is None


# ---- Regression: repeated identical request, planner paraphrases the title ----
# The user says "Put the work on the BAJA wiring task on my calendar" a second
# time. The planner may paraphrase task_title to "the BAJA wiring task" — which
# is genuinely ambiguous on its own. The server must resolve the user's ORIGINAL
# message verbatim ("work on the BAJA wiring"), never degrade to the ambiguous
# paraphrase, and must UPDATE the existing event rather than create a duplicate.
def test_chat_repeated_request_paraphrased_title_still_resolves_exact_task(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t2.google_calendar_event_id = "evt_from_first_request"
    db_session.commit()
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_from_first_request"}
        reply = _clarify(planner_payload, "Put the work on the BAJA wiring task on my calendar.", db_session)

    # The original message resolves to "work on the BAJA wiring" specifically,
    # so the correct task is updated — no ambiguity, no duplicate event.
    assert 'Added "work on the BAJA wiring" to your Google Calendar.' in reply
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    assert t2.google_calendar_event_id == "evt_from_first_request"
    assert t1.google_calendar_event_id is None
    assert t3.google_calendar_event_id is None


def test_chat_repeated_request_paraphrased_title_creates_when_not_linked(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_work"}) as mock_create:
        reply = _clarify(planner_payload, "Put the work on the BAJA wiring task on my calendar.", db_session)

    assert 'Added "work on the BAJA wiring" to your Google Calendar.' in reply
    mock_create.assert_called_once()
    assert t2.google_calendar_event_id == "evt_work"
    assert t1.google_calendar_event_id is None
    assert t3.google_calendar_event_id is None


# ---- Regression: ambiguous message stays ambiguous even if the planner ----
# ---- supplies a specific-looking title (server trusts the user's words). ----
def test_chat_ambiguous_message_not_overridden_by_specific_planner_title(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the work on the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        reply = _clarify(planner_payload, "Put the BAJA wiring task on my calendar.", db_session)

    # "the BAJA wiring task" alone is ambiguous between the two BAJA tasks.
    assert "multiple tasks" in reply
    assert "finish the BAJA wiring" in reply
    assert "work on the BAJA wiring" in reply
    assert "Which one should I add to the calendar?" in reply
    mock_create.assert_not_called()
    assert t1.google_calendar_event_id is None
    assert t2.google_calendar_event_id is None
    assert t3.google_calendar_event_id is None


def test_chat_finish_request_resolves_finish_even_with_paraphrased_title(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "the BAJA wiring task", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_finish"}) as mock_create:
        reply = _clarify(planner_payload, "Put the finish the BAJA wiring task on my calendar.", db_session)

    assert 'Added "finish the BAJA wiring" to your Google Calendar.' in reply
    mock_create.assert_called_once()
    assert t1.google_calendar_event_id == "evt_finish"
    assert t2.google_calendar_event_id is None


# ----------------------------------------------------------------------
# N. Unspecified scheduling: never invent a date/time (Phase 1)
# ----------------------------------------------------------------------
def _unlinked_task(db_session, title="finish the BAJA wiring"):
    task = Task(title=title, priority="medium")
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def test_add_task_to_calendar_without_schedule_asks_for_time(db_session):
    task = _unlinked_task(db_session)
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        result = add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(task_id=task.id))

    data = result["data"]
    assert data["reply_direct"] is True
    assert f"I found the task '{task.title}'." in data["error"]
    assert "When should I schedule it on your calendar?" in data["error"]
    mock_create.assert_not_called()
    assert task.google_calendar_event_id is None
    assert task.scheduled_start is None


def test_chat_put_task_without_schedule_asks_for_time(db_session):
    task = _unlinked_task(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "finish the BAJA wiring", "when": None, "start_time": None, "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        reply = _clarify(planner_payload, "Put finish the BAJA wiring on my calendar.", db_session)

    assert "finish the BAJA wiring" in reply
    assert "When should I schedule it on your calendar?" in reply
    mock_create.assert_not_called()
    assert task.google_calendar_event_id is None
    assert task.scheduled_start is None


def test_chat_put_task_tomorrow_at_time_creates_event(db_session):
    task = _unlinked_task(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "finish the BAJA wiring", "when": "tomorrow", "start_time": "16:00", "timezone": "Asia/Kolkata"},
    }
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_finish"}) as mock_create:
        reply = _clarify(planner_payload, "Put finish the BAJA wiring on my calendar tomorrow at 4 PM.", db_session)

    assert 'Added "finish the BAJA wiring" to your Google Calendar.' in reply
    mock_create.assert_called_once()
    event_body = mock_create.call_args.args[0]
    assert event_body["start"]["timeZone"] == "Asia/Kolkata"
    assert event_body["start"]["dateTime"].endswith("+05:30")
    assert task.google_calendar_event_id == "evt_finish"
    assert task.scheduled_start is not None


def test_add_task_to_calendar_explicit_date_and_time(db_session):
    task = _unlinked_task(db_session)
    with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_date"}) as mock_create:
        result = add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(
            task_id=task.id, when="2026-08-21", start_time="15:00", duration_minutes=60,
        ))

    body = mock_create.call_args.args[0]
    assert body["start"]["dateTime"].startswith("2026-08-21T15:00")
    assert body["end"]["dateTime"].startswith("2026-08-21T16:00")
    assert result["data"].google_calendar_event_id == "evt_date"


def test_task_deadline_alone_does_not_become_work_slot(db_session):
    task = Task(title="finish the BAJA wiring", priority="medium",
                deadline=datetime(2026, 8, 25, 9, 0))
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        result = add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(task_id=task.id))

    data = result["data"]
    assert data["reply_direct"] is True
    assert "When should I schedule it on your calendar?" in data["error"]
    mock_create.assert_not_called()
    assert task.google_calendar_event_id is None
    assert task.scheduled_start is None
    # The deadline is preserved and never turned into a work-session time.
    assert task.deadline is not None


def test_linked_task_update_with_explicit_schedule_remains_idempotent(db_session):
    task = _linked_task(db_session)  # already has google_calendar_event_id="evt_existing"
    with patch.object(google_calendar, "update_calendar_event") as mock_update, \
         patch.object(google_calendar, "create_calendar_event") as mock_create:
        mock_update.return_value = {"id": "evt_existing"}
        result = add_task_to_calendar_tool(db_session, AddTaskToCalendarRequest(
            task_id=task.id, when="tomorrow", start_time="10:00",
        ))

    assert result["data"].google_calendar_event_id == "evt_existing"
    mock_update.assert_called_once()
    mock_create.assert_not_called()


def test_create_task_schedule_without_time_does_not_create_event(db_session):
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Wiring", priority="medium", schedule_on_calendar=True,
        ))

    task = result["data"]
    assert task.id is not None
    assert task.google_calendar_event_id is None
    assert task.scheduled_start is None
    mock_create.assert_not_called()


def test_router_post_calendar_without_schedule_returns_400(db_session, client):
    task = _unlinked_task(db_session)
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        resp = client.post(f"/tasks/{task.id}/calendar", json={})

    assert resp.status_code == 400
    assert "When should I schedule it" in resp.json()["detail"]
    mock_create.assert_not_called()


# ----------------------------------------------------------------------
# O. Ambiguous-resolution UX: calendar state is shown, never used to pick
# ----------------------------------------------------------------------
def test_clarification_shows_calendar_state_both_unlinked(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    result = resolve_task_for_calendar(db_session, "the BAJA wiring task")
    assert result["status"] == "ambiguous"
    assert "finish the BAJA wiring — Not on calendar" in result["message"]
    assert "work on the BAJA wiring — Not on calendar" in result["message"]
    assert "Wiring Diagram" not in result["message"]


def test_clarification_shows_calendar_state_one_linked(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t2.google_calendar_event_id = "evt_work"
    db_session.commit()
    result = resolve_task_for_calendar(db_session, "the BAJA wiring task")
    assert result["status"] == "ambiguous"
    assert "finish the BAJA wiring — Not on calendar" in result["message"]
    assert "work on the BAJA wiring — 📅 On calendar" in result["message"]


def test_clarification_shows_calendar_state_both_linked(db_session):
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t1.google_calendar_event_id = "evt_finish"
    t2.google_calendar_event_id = "evt_work"
    db_session.commit()
    result = resolve_task_for_calendar(db_session, "the BAJA wiring task")
    assert result["status"] == "ambiguous"
    assert "finish the BAJA wiring — 📅 On calendar" in result["message"]
    assert "work on the BAJA wiring — 📅 On calendar" in result["message"]


def test_no_silent_selection_based_on_calendar_state(db_session):
    # One of the two BAJA tasks is already linked. The resolver must still be
    # ambiguous — calendar state is informational only and must never silently
    # pick the linked (or the unlinked) task.
    t1, t2, t3, t4 = _seed_wiring_tasks(db_session)
    t2.google_calendar_event_id = "evt_work"
    db_session.commit()

    result = resolve_task_for_calendar(db_session, "the BAJA wiring task")
    assert result["status"] == "ambiguous"
    assert [t.id for t in result["candidates"]] == [t1.id, t2.id]

    # And through the dispatcher: clarification, never a write.
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        exec_result = execute_tool(
            "add_task_to_calendar",
            {"task_title": "the BAJA wiring task", "when": "tomorrow"},
            db_session,
        )
    assert exec_result["data"]["reply_direct"] is True
    mock_create.assert_not_called()
    assert t1.google_calendar_event_id is None
    assert t2.google_calendar_event_id == "evt_work"


# ----------------------------------------------------------------------
# P. Problem 1/3: the planner must never fabricate a calendar event_id from
#    a task title. Move/reschedule requests route through the task-calendar
#    tools, and the server resolves the task + its linked event.
# ----------------------------------------------------------------------
def test_chat_normalizes_planner_fabricated_update_to_task_tool(db_session):
    task = _qa_scheduled_task(db_session)
    planner_payload = {
        "tool": "update_calendar_event",
        "args": {
            "event_id": "QA scheduled task",
            "when": "tomorrow",
            "start_time": "18:00",
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_qa_scheduled"}) as mock_update, \
             patch.object(google_calendar, "create_calendar_event") as mock_create:
            reply = chat_with_ai(
                [{"role": "user", "content": "Move QA scheduled task to tomorrow at 6 PM for one hour."}],
                db_session,
            )

    mock_create.assert_not_called()
    mock_update.assert_called_once()
    assert mock_update.call_args.args[0] == "evt_qa_scheduled"
    assert 'Moved "QA scheduled task" to your Google Calendar.' in reply


def test_chat_move_linked_task_updates_existing_event(db_session):
    task = _qa_scheduled_task(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {
            "task_title": "QA scheduled task",
            "when": "tomorrow",
            "start_time": "18:00",
            "duration_minutes": 60,
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_qa_scheduled"}) as mock_update, \
             patch.object(google_calendar, "create_calendar_event") as mock_create:
            reply = chat_with_ai(
                [{"role": "user", "content": "Move QA scheduled task to tomorrow at 6 PM for one hour."}],
                db_session,
            )

    mock_create.assert_not_called()
    mock_update.assert_called_once()
    assert mock_update.call_args.args[0] == "evt_qa_scheduled"
    assert 'Moved "QA scheduled task" to your Google Calendar.' in reply


def test_chat_move_unlinked_task_creates_event_once(db_session):
    task = _qa_scheduled_task(db_session, linked=False)
    planner_payload = {
        "tool": "update_calendar_event",
        "args": {
            "event_id": "QA scheduled task",
            "when": "tomorrow",
            "start_time": "18:00",
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "create_calendar_event", return_value={"id": "evt_moved"}) as mock_create, \
             patch.object(google_calendar, "update_calendar_event") as mock_update:
            reply = chat_with_ai(
                [{"role": "user", "content": "Move QA scheduled task to tomorrow at 6 PM for one hour."}],
                db_session,
            )

    mock_create.assert_called_once()
    mock_update.assert_not_called()
    db_session.refresh(task)
    assert task.google_calendar_event_id == "evt_moved"
    assert 'Moved "QA scheduled task" to your Google Calendar.' in reply


def test_reschedule_reply_says_moved_not_added(db_session):
    """A successful MOVE/RESCHEDULE must reply "Moved …", never "Added …".

    The underlying operation (same-event update, no duplicate) is unchanged;
    only the response wording is asserted here.
    """
    task = _qa_scheduled_task(db_session)
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {
            "task_title": "QA scheduled task",
            "when": "tomorrow",
            "start_time": "20:00",
            "duration_minutes": 60,
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_qa_scheduled"}) as mock_update, \
             patch.object(google_calendar, "create_calendar_event") as mock_create:
            reply = chat_with_ai(
                [{"role": "user", "content": "Move QA scheduled task to tomorrow at 8 PM for one hour."}],
                db_session,
            )

    assert 'Moved "QA scheduled task" to your Google Calendar.' in reply
    assert "Added" not in reply
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    db_session.refresh(task)
    assert task.google_calendar_event_id == "evt_qa_scheduled"


def test_reschedule_reply_via_planner_reroute_says_moved_not_added(db_session):
    """Reschedule requests that the planner mis-routes to update_calendar_event
    (fabricating the event id from the task title) must also render "Moved …"
    after the server re-routes them through add_task_to_calendar."""
    task = _qa_scheduled_task(db_session)
    planner_payload = {
        "tool": "update_calendar_event",
        "args": {
            "event_id": "QA scheduled task",
            "when": "tomorrow",
            "start_time": "20:00",
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_qa_scheduled"}) as mock_update, \
             patch.object(google_calendar, "create_calendar_event") as mock_create:
            reply = chat_with_ai(
                [{"role": "user", "content": "Move QA scheduled task to tomorrow at 8 PM for one hour."}],
                db_session,
            )

    assert 'Moved "QA scheduled task" to your Google Calendar.' in reply
    assert "Added" not in reply
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    db_session.refresh(task)
    assert task.google_calendar_event_id == "evt_qa_scheduled"


def test_add_reply_still_says_added_not_moved(db_session):
    """Fresh add/link requests must keep saying "Added …", never "Moved …"."""
    task = _linked_task(db_session, title="Wiring")  # linked but request is an add
    planner_payload = {
        "tool": "add_task_to_calendar",
        "args": {"task_title": "Wiring", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_existing"}) as mock_update, \
             patch.object(google_calendar, "create_calendar_event") as mock_create:
            reply = chat_with_ai(
                [{"role": "user", "content": "Put my Wiring task on my calendar tomorrow."}],
                db_session,
            )

    assert 'Added "Wiring" to your Google Calendar.' in reply
    assert "Moved" not in reply
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    db_session.refresh(task)
    assert task.google_calendar_event_id == "evt_existing"


def test_dispatcher_rejects_fabricated_event_id_no_google_call(db_session):
    _qa_scheduled_task(db_session)
    with patch.object(google_calendar, "update_calendar_event") as mock_update:
        result = execute_tool(
            "update_calendar_event",
            {"event_id": "QA scheduled task", "when": "tomorrow", "start_time": "18:00"},
            db_session,
        )

    assert "error" in result["data"]
    assert "not a known Google Calendar event id" in result["data"]["error"]
    mock_update.assert_not_called()


def test_dispatcher_reroutes_verified_linked_event_id(db_session):
    task = _qa_scheduled_task(db_session)
    with patch.object(google_calendar, "update_calendar_event", return_value={"id": "evt_qa_scheduled"}) as mock_update:
        result = execute_tool(
            "update_calendar_event",
            {"event_id": "evt_qa_scheduled", "when": "tomorrow", "start_time": "18:00", "timezone": "Asia/Kolkata"},
            db_session,
        )

    assert result["data"].id == task.id
    mock_update.assert_called_once()
    assert mock_update.call_args.args[0] == "evt_qa_scheduled"


# ----------------------------------------------------------------------
# Q. Problem 2: remove routes to remove_task_from_calendar. The server
#    resolves the task, deletes its linked event, keeps the task row and
#    clears the link. Unlinked tasks never cause a Google write.
# ----------------------------------------------------------------------
def test_chat_remove_task_deletes_event_keeps_task(db_session):
    task = _qa_scheduled_task(db_session)
    planner_payload = {"tool": "remove_task_from_calendar", "args": {"task_title": "QA scheduled task"}}
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "delete_calendar_event") as mock_delete, \
             patch.object(google_calendar, "create_calendar_event") as mock_create, \
             patch.object(google_calendar, "update_calendar_event") as mock_update:
            reply = chat_with_ai(
                [{"role": "user", "content": "Remove QA scheduled task from my calendar."}],
                db_session,
            )

    mock_delete.assert_called_once()
    assert mock_delete.call_args.args[0] == "evt_qa_scheduled"
    mock_create.assert_not_called()
    mock_update.assert_not_called()
    db_session.refresh(task)
    assert task.google_calendar_event_id is None
    assert task.calendar_sync_error is None
    assert 'Removed "QA scheduled task" from your Google Calendar.' in reply


def test_chat_remove_planner_misroutes_delete_event(db_session):
    task = _qa_scheduled_task(db_session)
    planner_payload = {"tool": "delete_calendar_event", "args": {"event_id": "QA scheduled task"}}
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
            reply = chat_with_ai(
                [{"role": "user", "content": "Remove QA scheduled task from my calendar."}],
                db_session,
            )

    mock_delete.assert_called_once()
    assert mock_delete.call_args.args[0] == "evt_qa_scheduled"
    db_session.refresh(task)
    assert task.google_calendar_event_id is None
    assert 'Removed "QA scheduled task" from your Google Calendar.' in reply


def test_remove_unlinked_task_no_write_not_linked_message(db_session):
    task = _qa_scheduled_task(db_session, linked=False)
    planner_payload = {"tool": "remove_task_from_calendar", "args": {"task_title": "QA scheduled task"}}
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
            reply = chat_with_ai(
                [{"role": "user", "content": "Remove QA scheduled task from my calendar."}],
                db_session,
            )

    mock_delete.assert_not_called()
    assert "isn't currently linked to a Google Calendar event" in reply


def test_remove_ambiguous_task_stays_ambiguous(db_session):
    _seed_wiring_tasks(db_session)
    planner_payload = {"tool": "remove_task_from_calendar", "args": {"task_title": "the BAJA wiring task"}}
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
            reply = chat_with_ai(
                [{"role": "user", "content": "Remove the BAJA wiring task from my calendar."}],
                db_session,
            )

    mock_delete.assert_not_called()
    assert "Which one should I remove from the calendar?" in reply


def test_dispatcher_delete_reroutes_linked_event(db_session):
    task = _qa_scheduled_task(db_session)
    with patch.object(google_calendar, "delete_calendar_event") as mock_delete:
        result = execute_tool("delete_calendar_event", {"event_id": "evt_qa_scheduled"}, db_session)

    assert result["data"].id == task.id
    mock_delete.assert_called_once()
    assert mock_delete.call_args.args[0] == "evt_qa_scheduled"
    db_session.refresh(task)
    assert task.google_calendar_event_id is None


# ----------------------------------------------------------------------
# R. Problem 4: op-specific failure messages (never one generic "couldn't add")
# ----------------------------------------------------------------------
def test_calendar_operation_failure_messages_are_op_specific():
    from app.services.ai_service import (
        _calendar_operation_failure_message,
        _CALENDAR_NOT_CREATED_MESSAGE,
        _CALENDAR_NOT_UPDATED_MESSAGE,
        _CALENDAR_NOT_REMOVED_MESSAGE,
    )
    assert _calendar_operation_failure_message("create_calendar_event") == _CALENDAR_NOT_CREATED_MESSAGE
    assert _calendar_operation_failure_message("update_calendar_event") == _CALENDAR_NOT_UPDATED_MESSAGE
    assert _calendar_operation_failure_message("delete_calendar_event") == _CALENDAR_NOT_REMOVED_MESSAGE


def test_task_calendar_operation_classification():
    from app.services.ai_service import _task_calendar_operation
    assert _task_calendar_operation("Put QA no time task on my calendar.") == "add"
    assert _task_calendar_operation("Move QA scheduled task to tomorrow at 6 PM for one hour.") == "reschedule"
    assert _task_calendar_operation("Remove QA scheduled task from my calendar.") == "remove"
    assert _task_calendar_operation("add this to my calendar") is None
    assert _task_calendar_operation("schedule a meeting tomorrow") is None
    assert _task_calendar_operation("remind me tomorrow at 9am to call the team") is None


def test_chat_update_failure_message_is_update_specific(db_session):
    planner_payload = {
        "tool": "update_calendar_event",
        "args": {"event_id": "some_real_event_id", "when": "tomorrow", "start_time": "15:00"},
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "_require_write_access"), \
             patch.object(google_calendar, "_get_service", side_effect=RuntimeError("network down")):
            reply = chat_with_ai(
                [{"role": "user", "content": "reschedule the meeting on my calendar to tomorrow at 3pm"}],
                db_session,
            )

    assert "couldn't update that calendar event" in reply
    assert "No changes were made" in reply
    assert "network down" not in reply


# ----------------------------------------------------------------------
# S. Problem 5: a planner failure (e.g. Groq 429) must never produce a fake
#    success — the reply is the honest op-specific failure message.
# ----------------------------------------------------------------------
def test_chat_planner_failure_remove_reports_honest_message(db_session):
    import httpx
    from groq import RateLimitError

    _qa_scheduled_task(db_session)
    request = httpx.Request("POST", "http://example.com")
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RateLimitError(
            message="too many requests",
            response=httpx.Response(429, request=request),
            body=None,
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=True), \
             patch("app.services.ai_service.get_upcoming_events", return_value=[]), \
             patch("app.services.google_calendar.has_write_scope", return_value=True), \
             patch("app.services.ai_service.execute_tool") as mock_execute:
            reply = chat_with_ai(
                [{"role": "user", "content": "Remove QA scheduled task from my calendar."}],
                db_session,
            )

    mock_execute.assert_not_called()
    assert "couldn't remove that task from Google Calendar" in reply
    assert "task itself was not deleted" in reply


def test_chat_planner_failure_reschedule_reports_honest_message(db_session):
    import httpx
    from groq import RateLimitError

    _qa_scheduled_task(db_session)
    request = httpx.Request("POST", "http://example.com")
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RateLimitError(
            message="too many requests",
            response=httpx.Response(429, request=request),
            body=None,
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=True), \
             patch("app.services.ai_service.get_upcoming_events", return_value=[]), \
             patch("app.services.google_calendar.has_write_scope", return_value=True), \
             patch("app.services.ai_service.execute_tool") as mock_execute:
            reply = chat_with_ai(
                [{"role": "user", "content": "Move QA scheduled task to tomorrow at 6 PM for one hour."}],
                db_session,
            )

    mock_execute.assert_not_called()
    assert "couldn't update that calendar event" in reply
    assert "No changes were made" in reply

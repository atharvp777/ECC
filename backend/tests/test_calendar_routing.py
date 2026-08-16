import json
from datetime import datetime, timedelta, date
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.services.ai_service import (
    plan_tool_call,
    chat_with_ai,
    _is_calendar_write_request,
)
from app.services import google_calendar
from app.services.tools import build_calendar_event_body
from app.core.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ----------------------------------------------------------------------
# Helpers
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
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _write_token(monkeypatch, tmp_path, scopes):
    """Create a fake google_token.json with the given scopes."""
    token_file = tmp_path / "google_token.json"
    token_file.write_text(json.dumps({
        "token": "fake_token",
        "refresh_token": "fake_refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "cs",
        "scopes": scopes,
    }))
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", token_file)
    return token_file


_WRITE_TOKEN = ("https://www.googleapis.com/auth/calendar.events",)
_READONLY_TOKEN = ("https://www.googleapis.com/auth/calendar.readonly",)


# ----------------------------------------------------------------------
# 1. Planner routing
# ----------------------------------------------------------------------
def test_planner_prompt_exposes_calendar_tools():
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response("NONE")
        mock_groq_class.return_value = mock_client

        plan_tool_call("hello", "ctx")
        prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]

        for tool in (
            "list_calendar_events",
            "create_calendar_event",
            "update_calendar_event",
            "delete_calendar_event",
        ):
            assert tool in prompt
        assert "Do NOT convert a calendar request into create_task" in prompt
        assert "remind me tomorrow" in prompt
        assert "what are my calendar events?" in prompt
        assert "Asia/Kolkata" in prompt
        assert "UTC+05:30" in prompt


@pytest.mark.parametrize(
    "user_msg,expected_tool,when",
    [
        ("add a reminder for tomorrow to get white shirt from ayu", "create_calendar_event", "tomorrow"),
        ("schedule a meeting tomorrow", "create_calendar_event", "tomorrow"),
        ("add this to my calendar", "create_calendar_event", None),
    ],
)
def test_planner_routes_calendar_writes(user_msg, expected_tool, when):
    args = {
        "summary": "Get white shirt from ayu",
        "description": None,
        "when": when,
        "start_time": None,
        "duration_minutes": 60,
        "timezone": "Asia/Kolkata",
    }
    payload = {"tool": expected_tool, "args": args}
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, "ctx")
        assert result is not None
        assert result["tool"] == expected_tool


def test_planner_routes_task_to_create_task():
    payload = {
        "tool": "create_task",
        "args": {
            "title": "Finish the wiring diagram",
            "priority": "MEDIUM",
            "deadline": None,
            "project_name": None,
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call("create a task to finish the wiring diagram", "ctx")
        assert result is not None
        assert result["tool"] == "create_task"


def test_planner_routes_calendar_read_to_list():
    payload = {"tool": "list_calendar_events", "args": {}}
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(payload))
        mock_groq_class.return_value = mock_client

        result = plan_tool_call("what's on my calendar?", "ctx")
        assert result is not None
        assert result["tool"] == "list_calendar_events"


def test_calendar_write_request_detector():
    assert _is_calendar_write_request("add a reminder for tomorrow to get white shirt from ayu")
    assert _is_calendar_write_request("schedule a meeting tomorrow")
    assert _is_calendar_write_request("add this to my calendar")
    assert _is_calendar_write_request("remind me tomorrow at 9am to call the team")
    assert not _is_calendar_write_request("create a task to finish the wiring diagram")
    assert not _is_calendar_write_request("what's on my calendar?")
    assert not _is_calendar_write_request("remind me to review the PR")


# ----------------------------------------------------------------------
# 2. Date handling (deterministic server-side resolution, UTC+05:30)
# ----------------------------------------------------------------------
def test_resolve_event_body_tomorrow():
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    body = build_calendar_event_body({
        "summary": "Pick up white shirt",
        "when": "tomorrow",
        "timezone": "Asia/Kolkata",
    })
    expected_date = (now.date() + timedelta(days=1)).isoformat()
    assert body["summary"] == "Pick up white shirt"
    assert body["start"]["timeZone"] == "Asia/Kolkata"
    assert body["start"]["dateTime"].startswith(expected_date)
    assert body["start"]["dateTime"].endswith("+05:30")


def test_resolve_event_body_explicit_date():
    body = build_calendar_event_body({
        "summary": "Exam",
        "when": "2026-08-20",
        "start_time": "10:00",
        "duration_minutes": 120,
        "timezone": "Asia/Kolkata",
    })
    assert body["start"]["dateTime"].startswith("2026-08-20T10:00")
    assert body["end"]["dateTime"].startswith("2026-08-20T12:00")
    assert body["start"]["dateTime"].endswith("+05:30")


def test_resolve_event_body_timezone_offset():
    body = build_calendar_event_body({
        "summary": "Standup",
        "when": "tomorrow",
        "start_time": "09:00",
        "timezone": "Asia/Kolkata",
    })
    assert body["start"]["dateTime"].endswith("+05:30")
    assert body["end"]["dateTime"].endswith("+05:30")


def test_resolve_event_body_verbatim_event_data_passthrough():
    existing = {
        "summary": "Direct",
        "start": {"dateTime": "2026-08-20T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-08-20T11:00:00+05:30", "timeZone": "Asia/Kolkata"},
    }
    body = build_calendar_event_body({"event_data": existing})
    assert body is not None
    assert body["summary"] == "Direct"
    assert body["start"]["dateTime"] == "2026-08-20T10:00:00+05:30"


# ----------------------------------------------------------------------
# 3. Calendar write success (mocked Google)
# ----------------------------------------------------------------------
def test_create_calendar_event_success_uses_returned_event_id(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, _WRITE_TOKEN)
    mock_service = MagicMock()
    created = {
        "id": "evt_abc123",
        "summary": "Pick up white shirt",
        "start": {"dateTime": "2026-08-17T09:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-08-17T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "status": "confirmed",
    }
    insert_mock = mock_service.events().insert
    insert_mock.return_value.execute.return_value = created

    with patch.object(google_calendar, "_get_service", return_value=mock_service):
        result = google_calendar.create_calendar_event({
            "summary": "Pick up white shirt",
            "start": {"dateTime": "2026-08-17T09:00:00+05:30", "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": "2026-08-17T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
        })

    assert result["id"] == "evt_abc123"
    assert result["status"] == "confirmed"
    insert_mock.assert_called_once()
    _, kwargs = insert_mock.call_args
    assert kwargs["calendarId"] == "primary"


def test_chat_reports_success_only_after_api_event_id(db_session):
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "Pick up white shirt",
            "when": "tomorrow",
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": {
                "id": "evt_xyz",
                "summary": "Pick up white shirt",
                "start": {"dateTime": "2026-08-17T09:00:00+05:30", "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": "2026-08-17T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
                "status": "confirmed",
            }}
            reply = chat_with_ai(
                [{"role": "user", "content": "add a reminder for tomorrow to get white shirt from ayu"}],
                db_session,
            )

    assert "Created calendar event" in reply
    assert "Pick up white shirt" in reply
    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[0] == "create_calendar_event"


def test_chat_never_reports_success_without_event_id(db_session):
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {"summary": "x", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            # A "success" result with no event ID must NOT be reported as success.
            mock_execute.return_value = {"data": {"summary": "x", "start": {}, "end": {}}}
            reply = chat_with_ai(
                [{"role": "user", "content": "add this to my calendar"}],
                db_session,
            )

    assert "Created calendar event" not in reply
    assert "No calendar event was created" in reply


# ----------------------------------------------------------------------
# 4. Calendar write failure (mocked Google API failure)
# ----------------------------------------------------------------------
def test_chat_calendar_write_failure_is_honest(db_session, monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, _WRITE_TOKEN)
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {"summary": "x", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    mock_service = MagicMock()
    mock_service.events().insert().execute.side_effect = RuntimeError("network down")

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "_get_service", return_value=mock_service):
            reply = chat_with_ai(
                [{"role": "user", "content": "add this to my calendar"}],
                db_session,
            )

    assert "Created calendar event" not in reply
    assert "No calendar event was created" in reply
    assert "network down" not in reply


# ----------------------------------------------------------------------
# 5. Missing write scope (calendar.readonly token)
# ----------------------------------------------------------------------
def test_has_write_scope_readonly_is_false(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, _READONLY_TOKEN)
    assert google_calendar.has_write_scope() is False


def test_has_write_scope_write_is_true(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, _WRITE_TOKEN)
    assert google_calendar.has_write_scope() is True


def test_has_write_scope_full_calendar_scope_is_true(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, ("https://www.googleapis.com/auth/calendar",))
    assert google_calendar.has_write_scope() is True


def test_has_write_scope_no_token_is_false(monkeypatch, tmp_path):
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", tmp_path / "nope.json")
    assert google_calendar.has_write_scope() is False


@pytest.mark.parametrize("func_name,args", [
    ("create_calendar_event", ({"summary": "x"},)),
    ("update_calendar_event", ("evt1", {"summary": "x"})),
    ("delete_calendar_event", ("evt1",)),
])
def test_write_ops_fail_clearly_with_readonly_scope(monkeypatch, tmp_path, func_name, args):
    _write_token(monkeypatch, tmp_path, _READONLY_TOKEN)
    with patch.object(google_calendar, "_get_service") as mock_get_service:
        with pytest.raises(PermissionError) as excinfo:
            getattr(google_calendar, func_name)(*args)
        assert "write access isn't authorized" in str(excinfo.value)
        # The Google write API must not be called for a read-only token.
        mock_get_service.assert_not_called()


def test_chat_missing_write_scope_honest_message(db_session, monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, _READONLY_TOKEN)
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {"summary": "x", "when": "tomorrow", "timezone": "Asia/Kolkata"},
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "_get_service") as mock_get_service:
            reply = chat_with_ai(
                [{"role": "user", "content": "add a reminder for tomorrow to get white shirt from ayu"}],
                db_session,
            )

    assert "write access isn't authorized" in reply
    assert "reconnect" in reply
    assert "Created calendar event" not in reply
    mock_get_service.assert_not_called()


# ----------------------------------------------------------------------
# Specific regression: the exact previous failure can no longer happen
# ----------------------------------------------------------------------
def test_reminder_request_never_becomes_task_or_fake_success(db_session):
    """'add a reminder for tomorrow to get white shirt from ayu' must not:
    1. create a task,
    2. claim a calendar event was created without calling Google,
    3. fabricate 'Added to calendar'."""
    # Simulate the OLD buggy routing: planner picks create_task.
    planner_payload = {
        "tool": "create_task",
        "args": {"title": "Get white shirt from ayu", "priority": "MEDIUM", "deadline": None, "project_name": None},
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            reply = chat_with_ai(
                [{"role": "user", "content": "add a reminder for tomorrow to get white shirt from ayu"}],
                db_session,
            )

    # No task tool may have run.
    mock_execute.assert_not_called()
    assert "Created task" not in reply
    assert "Added to calendar" not in reply
    assert "Created calendar event" not in reply
    assert "calendar" in reply.lower()


def test_reminder_request_with_no_tool_cannot_let_llm_fabricate(db_session, monkeypatch, tmp_path):
    """If the planner returns nothing, the free-form LLM must never get a chance
    to claim the event was created."""
    # Force the not-connected state so the guard path is deterministic.
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", tmp_path / "missing.json")

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response("NONE")
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            reply = chat_with_ai(
                [{"role": "user", "content": "add a reminder for tomorrow to get white shirt from ayu"}],
                db_session,
            )

    # Planner call happened (1 Groq call), but the free-form LLM call never ran.
    assert mock_client.chat.completions.create.call_count == 1
    mock_execute.assert_not_called()
    assert "isn't connected" in reply
    assert "no calendar event was created" in reply.lower() or "connect it" in reply.lower()


def test_reminder_request_success_path_still_works(db_session):
    """With proper routing + a successful Google write, the reminder flow works."""
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "Get white shirt from ayu",
            "description": None,
            "when": "tomorrow",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": "Asia/Kolkata",
        },
    }
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": {
                "id": "evt_success_1",
                "summary": "Get white shirt from ayu",
                "start": {"dateTime": "2026-08-17T09:00:00+05:30", "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": "2026-08-17T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
                "status": "confirmed",
            }}
            reply = chat_with_ai(
                [{"role": "user", "content": "add a reminder for tomorrow to get white shirt from ayu"}],
                db_session,
            )

    assert "Created calendar event" in reply
    assert "Get white shirt from ayu" in reply

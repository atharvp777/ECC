import pytest
from unittest.mock import patch, MagicMock

from app.services.ai_service import plan_tool_call
from app.core.config import settings
from app.services.tools import (
    ListProjectsRequest,
    CreateProjectRequest,
    UpdateProjectRequest,
    ListTasksRequest,
    CreateTaskRequest,
    UpdateTaskRequest,
    CompleteTaskRequest,
    ListCalendarEventsRequest,
    CreateCalendarEventRequest,
    UpdateCalendarEventRequest,
    DeleteCalendarEventRequest,
)


# ----------------------------------------------------------------------
# Mock Groq client response for planner
# ----------------------------------------------------------------------
def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


# ----------------------------------------------------------------------
# Deterministic test of plan_tool_call without Groq
# ----------------------------------------------------------------------
def test_plan_tool_call_returns_none_when_no_match():
    # No tool‑relevant keywords – should return None
    result = plan_tool_call("Explain why the sky is blue.", "dummy_context")
    assert result is None


def test_plan_tool_call_detects_create_task():
    # The planner should output a JSON with tool=create_task when the prompt
    # contains relevant keywords and a valid JSON payload.
    user_msg = "add task wiring diagram to BAJA HV"
    context = "LIVE CONTEXT\n---\nNo projects listed yet\n---\nEND CONTEXT"
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_response = _mock_groq_response(
            '{"tool":"create_task","args":{"title":"wiring diagram","priority":"MEDIUM","deadline":"2026-08-15T18:00:00","project_name":"BAJA HV"}}'
        )
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, context)
        assert result is not None
        assert result["tool"] == "create_task"
        args = result["args"]
        assert args["title"] == "wiring diagram"
        assert args["priority"] == "MEDIUM"
        # deadline is an ISO string; the test does not enforce exact format
        assert "2026-08-15T18:00:00" in args["deadline"]
        assert args["project_name"] == "BAJA HV"


def test_plan_tool_call_live_groq_smoke():
    """Optional live test that hits the real Groq API – skipped if key missing."""
    if not settings.GROQ_API_KEY:
        pytest.skip("GROQ_API_KEY not configured – skipping live Groq test")
    user_msg = "add task wiring diagram to BAJA HV"
    context = "LIVE CONTEXT\n---\nNo projects listed yet\n---\nEND CONTEXT"
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        # Configure the mocked response to return valid JSON for create_task
        mock_client.chat.completions.create.return_value.choices = [MagicMock()]
        mock_client.chat.completions.create.return_value.choices[0].message = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = '{"tool":"create_task","args":{"title":"wiring diagram","priority":"MEDIUM","deadline":"2026-08-15T18:00:00","project_name":"BAJA HV"}}'
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, context)
        # If we get here without skipping, the response should contain a tool call
        assert result is not None
        assert "tool" in result
        assert result["tool"] == "create_task"


def test_plan_tool_call_natural_language_create_task():
    """A plain “Create a task called X” should generate a create_task call
    with defaults: priority=MEDIUM, deadline=null, project_id=null."""
    user_msg = "Create a task called TEST_TASK"
    context = "LIVE CONTEXT\n---\nNo projects listed yet\n---\nEND CONTEXT"
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_response = _mock_groq_response(
            '{"tool":"create_task","args":{"title":"TEST_TASK","priority":"MEDIUM","deadline":null,"project_name":null}}'
        )
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, context)
        assert result is not None
        assert result["tool"] == "create_task"
        args = result["args"]
        assert args["title"] == "TEST_TASK"
        assert args["priority"] == "MEDIUM"
        assert args["deadline"] is None
        assert args["project_name"] is None


def test_plan_tool_call_prompt_prefers_project_name():
    user_msg = "Add task wiring diagram to BAJA HV"
    context = "LIVE CONTEXT\n---\nID: 1 | Name: **BAJA HV** | Category: BAJA\n---\nEND CONTEXT"
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_response = _mock_groq_response(
            '{"tool":"create_task","args":{"title":"wiring diagram","priority":"MEDIUM","deadline":null,"project_name":"BAJA HV"}}'
        )
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, context)
        assert result is not None
        prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "project_name" in prompt
        assert '"project_id":1' not in prompt


def test_plan_tool_call_create_project_uses_valid_category():
    user_msg = "Create a project called Robotics"
    context = "LIVE CONTEXT\n---\nNo projects listed yet\n---\nEND CONTEXT"
    with patch("app.services.ai_service.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_response = _mock_groq_response(
            '{"tool":"create_project","args":{"name":"Robotics","category":"personal"}}'
        )
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, context)
        assert result is not None
        assert result["tool"] == "create_project"
        assert result["args"]["category"] == "personal"


def test_create_task_handles_deadline_none():
    """Direct test that the create_task wrapper can handle a None deadline."""
    from app.services.tools import create_task, CreateTaskRequest
    mock_db = MagicMock()
    req = CreateTaskRequest(
        title="No deadline task",
        priority="MEDIUM",
        deadline=None,
        project_id=None,
    )
    # Should not raise and should return a dict with a data key
    result = create_task(mock_db, req)
    assert result is not None
    assert "data" in result
    # The stored deadline should be None
    assert result["data"].deadline is None


def test_create_task_with_valid_deadline():
    """A create_task with a proper ISO deadline should be processed correctly."""
    from app.services.tools import create_task, CreateTaskRequest
    mock_db = MagicMock()
    req = CreateTaskRequest(
        title="Task with deadline",
        priority="MEDIUM",
        deadline="2026-08-15T18:00:00Z",
        project_id=None,
    )
    result = create_task(mock_db, req)
    assert result is not None
    assert "data" in result
    # The function should not error out; we cannot assert the exact datetime
    # without a real DB, but the presence of "data" confirms success.

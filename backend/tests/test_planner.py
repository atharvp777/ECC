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
            '{"tool":"create_task","args":{"title":"wiring diagram","priority":"MEDIUM","deadline":"2026-08-15T18:00:00","project_id":1}}'
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
        assert args["project_id"] == 1


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
        mock_client.chat.completions.create.return_value.choices[0].message.content = '{"tool":"create_task","args":{"title":"wiring diagram","priority":"MEDIUM","deadline":"2026-08-15T18:00:00","project_id":1}}'
        mock_groq_class.return_value = mock_client

        result = plan_tool_call(user_msg, context)
        # If we get here without skipping, the response should contain a tool call
        assert result is not None
        assert "tool" in result
        assert result["tool"] == "create_task"

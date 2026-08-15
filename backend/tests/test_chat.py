import pytest
from unittest.mock import patch, MagicMock

from app.services.ai_service import chat_with_ai
from app.core.config import settings
from app.services.tools import execute_tool
from app.core.database import SessionLocal, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ----------------------------------------------------------------------
# Helper: isolated DB for chat tests (no production impact)
# ----------------------------------------------------------------------
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ----------------------------------------------------------------------
# Mock Groq to avoid real network calls
# ----------------------------------------------------------------------
def _mock_groq_chat_completion(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


def test_chat_normal_path(db_session):
    """Verify that a plain user message results in a Groq‑generated reply."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_chat_completion(
            "Simple reply from mock"
        )
        mock_groq.return_value = mock_client

        # Minimal context – no live DB needed for this deterministic test
        messages = [{"role": "user", "content": "Hello"}]
        reply = chat_with_ai(messages, db_session)
        assert "Simple reply from mock" in reply
        # Ensure the function returned a string, not an exception


def test_chat_explicit_create_task_path(db_session):
    """Verify that a message that triggers a tool call results in a proper response."""
    # First, ensure a project exists for FK reference
    from app.models.project import Project
    proj = Project(name="TestProj", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        # Mock planner to return a create_task tool call
        planner_json = (
            '{"tool":"create_task","args":{"title":"TestTask","priority":"MEDIUM",'
            '"deadline":"2025-01-01T00:00:00","project_id":1}}'
        )
        mock_client.chat.completions.create.return_value.choices[0].message.content = planner_json
        mock_groq.return_value = mock_client

        # Mock the actual tool execution – we want it to return a fake result
        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": {"id": 1, "title": "TestTask"}}
            messages = [
                {"role": "user", "content": "create a task called TestTask for TestProj"},
            ]
            reply = chat_with_ai(messages, db_session)
            # The reply should mention that the task was created
            assert "created" in reply.lower()
            # Ensure execute_tool was called with the correct tool name
            mock_execute.assert_called_once()
            called_args = mock_execute.call_args[1]["args"]
            assert called_args["tool_name"] == "create_task"


def test_chat_tool_execution_result_is_user_facing(db_session):
    """Check that the result of a tool execution is turned into a user‑visible message."""
    # Seed a project
    from app.models.project import Project
    proj = Project(name="DemoProj", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        planner_json = (
            '{"tool":"complete_task","args":{"task_id":1}}'
        )
        mock_client.chat.completions.create.return_value.choices[0].message.content = planner_json
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            # Simulate completing task 1
            mock_execute.return_value = {"data": {"status": "DONE"}}
            messages = [{"role": "user", "content": "complete task 1"})
            reply = chat_with_ai(messages, db_session)
            assert "completed" in reply.lower()
            mock_execute.assert_called_once()

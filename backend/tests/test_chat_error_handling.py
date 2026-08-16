import httpx
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.services.ai_service import chat_with_ai, AIServiceError
from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _groq_conn_error(message="connection boom"):
    from groq import APIConnectionError
    return APIConnectionError(message=message, request=httpx.Request("POST", "http://example.com"))


def _groq_rate_limit_error(message="too many"):
    from groq import RateLimitError
    request = httpx.Request("POST", "http://example.com")
    return RateLimitError(message=message, response=httpx.Response(429, request=request), body=None)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _mock_reply(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


# ----------------------------------------------------------------------
# Service-level tests
# ----------------------------------------------------------------------
def test_chat_success(db_session):
    """A successful AI request returns the normal reply unchanged."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_reply("Simple reply from mock")
        mock_groq.return_value = mock_client

        reply = chat_with_ai([{"role": "user", "content": "Hello"}], db_session)
        assert reply == "Simple reply from mock"


def test_chat_provider_failure_is_safe(db_session):
    """Provider/network failures must surface a safe message, not a traceback."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _groq_conn_error()
        mock_groq.return_value = mock_client

        with pytest.raises(AIServiceError) as excinfo:
            chat_with_ai([{"role": "user", "content": "Hello"}], db_session)

        assert "connection boom" not in str(excinfo.value)
        assert "reach the AI service" in str(excinfo.value)


def test_chat_planner_failure_degrades_to_llm(db_session):
    """If the tool planner fails, chat should fall back to the normal LLM call."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _groq_conn_error(),   # planner call fails
            _mock_reply("Reply from the general LLM"),
        ]
        mock_groq.return_value = mock_client

        reply = chat_with_ai([{"role": "user", "content": "Hello"}], db_session)
        assert "general LLM" in reply


def test_chat_tool_execution_crash_is_safe(db_session):
    """Unexpected tool-execution crashes must not leak internal details."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.side_effect = RuntimeError("secret internal state leaked")
            reply = chat_with_ai(
                [{"role": "user", "content": '/tool complete_task {"task_id": 1}'}],
                db_session,
            )

        assert "secret internal state" not in reply
        assert "unexpected error" in reply.lower()


def test_chat_tool_error_result_not_swallowed(db_session):
    """Tool error results must remain user-facing, not turned into fake success."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.execute_tool") as mock_execute:
            mock_execute.return_value = {"data": {"error": "Project not found: Nope"}}
            reply = chat_with_ai(
                [{"role": "user", "content": '/tool create_task {"title": "x", "project_name": "Nope"}'}],
                db_session,
            )

        assert "Project not found: Nope" in reply
        assert "failed" in reply.lower()


def test_chat_malformed_ai_response_is_safe(db_session):
    """Empty/malformed AI content must become a safe message, not a crash."""
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_reply(None)
        mock_groq.return_value = mock_client

        with pytest.raises(AIServiceError) as excinfo:
            chat_with_ai([{"role": "user", "content": "Hello"}], db_session)

        assert "unexpected" in str(excinfo.value)


def test_chat_missing_api_key_returns_configured_message(db_session, monkeypatch):
    """Missing credentials must produce a clear configuration message."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    reply = chat_with_ai([{"role": "user", "content": "Hello"}], db_session)
    assert "isn't configured" in reply


# ----------------------------------------------------------------------
# Route-level tests (response contract preserved)
# ----------------------------------------------------------------------
@pytest.fixture
def chat_client():
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
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_chat_route_returns_200_with_safe_message_on_provider_failure(chat_client):
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _groq_rate_limit_error()
        mock_groq.return_value = mock_client

        response = chat_client.post(
            "/api/chat/",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"reply", "sources"}
    assert payload["sources"] == []
    assert "rate-limited" in payload["reply"]


def test_chat_route_returns_200_with_safe_message_on_unexpected_failure(chat_client):
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("traceback here")
        mock_groq.return_value = mock_client

        response = chat_client.post(
            "/api/chat/",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "traceback here" not in payload["reply"]
    assert "unexpected" in payload["reply"]
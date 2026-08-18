"""AI provider abstraction tests (Gemini primary, Groq fallback).

The Gemini API is fully mocked — the real Gemini API is never called from the
test suite. The Groq-based tests in the other suites continue to exercise the
fallback provider unchanged.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.services import ai_providers
from app.services.ai_providers import AIProviderError, complete_text, is_configured
from app.services.ai_service import chat_with_ai, plan_tool_call


def _mock_gemini_response(text):
    response = MagicMock()
    response.text = text
    return response


@pytest.fixture
def gemini_env(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "AI_MODEL", "gemini-3.6-flash")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")


@pytest.fixture
def mock_gemini_client():
    with patch.object(ai_providers, "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        yield client


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


def _chat_guard():
    return patch("app.services.ai_service.is_connected", return_value=False)


# ----------------------------------------------------------------------
# Gemini client initialization
# ----------------------------------------------------------------------
def test_gemini_client_initialization(gemini_env):
    with patch("google.genai.Client") as mock_client_class:
        client = ai_providers._gemini_client()
    mock_client_class.assert_called_once_with(api_key="test-key")
    assert client is mock_client_class.return_value


# ----------------------------------------------------------------------
# Simple Gemini response
# ----------------------------------------------------------------------
def test_gemini_simple_response(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("Hello from Gemini")
    text = complete_text(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1024,
        temperature=0.7,
    )
    assert text == "Hello from Gemini"
    call = mock_gemini_client.models.generate_content.call_args
    assert call.kwargs["model"] == "gemini-3.6-flash"
    config = call.kwargs["config"]
    assert config.system_instruction == "sys"
    assert config.max_output_tokens == 1024
    assert config.temperature == 0.7
    contents = call.kwargs["contents"]
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"][0]["text"] == "hi"


def test_gemini_converts_assistant_history(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("ok")
    complete_text(
        system="s",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        max_tokens=1024,
        temperature=0.7,
    )
    contents = mock_gemini_client.models.generate_content.call_args.kwargs["contents"]
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"


# ----------------------------------------------------------------------
# Planner / tool-call parsing
# ----------------------------------------------------------------------
def test_gemini_planner_tool_call_parsing(gemini_env, mock_gemini_client):
    payload = {"tool": "create_task", "args": {"title": "Wiring", "priority": "MEDIUM"}}
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response(json.dumps(payload))
    result = plan_tool_call("create a task called Wiring", "ctx")
    assert result == payload


def test_gemini_planner_none_response(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("NONE")
    assert plan_tool_call("hello", "ctx") is None


# ----------------------------------------------------------------------
# Malformed / empty Gemini responses
# ----------------------------------------------------------------------
def test_gemini_malformed_response_is_safe(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("not json at all")
    assert plan_tool_call("create a task x", "ctx") is None


def test_gemini_empty_response_is_safe(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("")
    assert plan_tool_call("create a task x", "ctx") is None


# ----------------------------------------------------------------------
# Gemini API failures → safe AIProviderError, never a fake success
# ----------------------------------------------------------------------
def test_gemini_api_failure_raises_safe_error(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.side_effect = RuntimeError("secret traceback here")
    with pytest.raises(AIProviderError) as excinfo:
        complete_text(system="s", messages=[{"role": "user", "content": "hi"}], max_tokens=1024, temperature=0.7)
    assert "secret traceback here" not in str(excinfo.value)


def test_gemini_rate_limit_is_safe(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.side_effect = RuntimeError("429 rate limit reached")
    with pytest.raises(AIProviderError) as excinfo:
        complete_text(system="s", messages=[{"role": "user", "content": "hi"}], max_tokens=1024, temperature=0.7)
    assert "rate-limited" in str(excinfo.value)


# ----------------------------------------------------------------------
# Missing GEMINI_API_KEY
# ----------------------------------------------------------------------
def test_gemini_missing_api_key_not_configured(gemini_env, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert is_configured() is False
    assert "GEMINI_API_KEY" in ai_providers.configured_message()


def test_gemini_missing_key_chat_returns_configured_message(gemini_env, monkeypatch, db_session):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with _chat_guard():
        reply = chat_with_ai([{"role": "user", "content": "Hello"}], db_session)
    assert "isn't configured" in reply
    assert "GEMINI_API_KEY" in reply


# ----------------------------------------------------------------------
# Gemini end-to-end via the existing chat service
# ----------------------------------------------------------------------
def test_gemini_chat_uses_provider_for_fallback(gemini_env, mock_gemini_client, db_session):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("Gemini reply")
    with _chat_guard():
        reply = chat_with_ai([{"role": "user", "content": "hello there"}], db_session)
    assert reply == "Gemini reply"
    assert mock_gemini_client.models.generate_content.call_args.kwargs["model"] == "gemini-3.6-flash"


# ----------------------------------------------------------------------
# Groq fallback keeps working (AI_PROVIDER=groq)
# ----------------------------------------------------------------------
def test_groq_provider_still_works(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")
    with patch("app.services.ai_service.Groq") as mock_groq:
        client = MagicMock()
        mock_groq.return_value = client
        text = complete_text(
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1024,
            temperature=0.7,
        )
    assert text == client.chat.completions.create.return_value.choices[0].message.content
    assert mock_groq.call_args.kwargs["api_key"] == "gsk-test"


# ----------------------------------------------------------------------
# Vision support & multimodal (text + inline image) generation
# ----------------------------------------------------------------------
def test_supports_vision_gemini_true(gemini_env):
    assert ai_providers.supports_vision() is True


def test_supports_vision_groq_false(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    assert ai_providers.supports_vision() is False


def test_multimodal_without_images_delegates_to_text(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("plain reply")
    text = ai_providers.complete_text_multimodal(
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        images=[],
    )
    assert text == "plain reply"
    contents = mock_gemini_client.models.generate_content.call_args.kwargs["contents"]
    assert contents[0]["parts"] == [{"text": "hi"}]


def test_multimodal_attaches_inline_images_to_last_user_turn(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value = _mock_gemini_response("I see a diagram")
    ai_providers.complete_text_multimodal(
        system="s",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "what does the image show"},
        ],
        images=[
            {"mime_type": "image/png", "data": b"\x89PNG\r\n\x1a\n"},
            {"mime_type": "image/jpeg", "data": b"\xff\xd8\xff"},
        ],
    )
    contents = mock_gemini_client.models.generate_content.call_args.kwargs["contents"]
    assert contents[-1]["role"] == "user"
    assert contents[-1]["parts"][0]["text"] == "what does the image show"
    assert contents[-1]["parts"][1] == {
        "inline_data": {"mime_type": "image/png", "data": b"\x89PNG\r\n\x1a\n"}
    }
    assert contents[-1]["parts"][2] == {
        "inline_data": {"mime_type": "image/jpeg", "data": b"\xff\xd8\xff"}
    }
    # earlier turns never receive image parts
    for turn in contents[:-1]:
        assert all("inline_data" not in part for part in turn["parts"])


def test_multimodal_groq_raises_vision_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")
    with pytest.raises(AIProviderError) as excinfo:
        ai_providers.complete_text_multimodal(
            system="s",
            messages=[{"role": "user", "content": "what does the image show"}],
            images=[{"mime_type": "image/png", "data": b"\x89PNG\r\n\x1a\n"}],
        )
    assert "cannot inspect image content" in str(excinfo.value)


def test_multimodal_api_failure_is_safe(gemini_env, mock_gemini_client):
    mock_gemini_client.models.generate_content.side_effect = RuntimeError("secret traceback here")
    with pytest.raises(AIProviderError) as excinfo:
        ai_providers.complete_text_multimodal(
            system="s",
            messages=[{"role": "user", "content": "what does the image show"}],
            images=[{"mime_type": "image/png", "data": b"\x89PNG\r\n\x1a\n"}],
        )
    assert "secret traceback here" not in str(excinfo.value)
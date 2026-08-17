"""AI provider abstraction for the Engineering Command Center.

ECC talks to exactly one LLM backend at a time, chosen by ``settings.AI_PROVIDER``:

- ``gemini`` (primary) — Google Gemini via the official ``google-genai`` SDK.
  The exact model is ``settings.AI_MODEL`` (default ``gemini-3.5-flash-lite``).
- ``groq`` (fallback) — Groq ``llama-3.3-70b-versatile``.

The rest of ECC only calls ``complete_text`` (plus the small configuration
helpers). This module picks the backend, converts the caller's ``system``
prompt + message list into the provider's expected input, and normalizes
provider failures into safe ``AIProviderError`` messages so the existing
honest failure handling keeps working unchanged.

The Groq client is resolved through ``app.services.ai_service.Groq`` at call
time so the existing test surface (``patch("app.services.ai_service.Groq")``)
continues to intercept provider calls.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class AIProviderError(Exception):
    """Safe, user-facing AI provider failure.

    The real exception is logged by ``complete_text``; only the safe message
    ever reaches the user.
    """


def is_configured() -> bool:
    """True when the active provider has its API key configured."""
    if settings.AI_PROVIDER == "gemini":
        return bool(settings.GEMINI_API_KEY)
    return bool(settings.GROQ_API_KEY)


def configured_message() -> str:
    """Instruction shown when the active provider is not configured."""
    key = "GEMINI_API_KEY" if settings.AI_PROVIDER == "gemini" else "GROQ_API_KEY"
    return (
        "The AI service isn't configured yet. "
        f"Add {key} to backend/.env and restart the backend."
    )


def active_model() -> str:
    """The model name for the active provider."""
    if settings.AI_PROVIDER == "gemini":
        return settings.AI_MODEL or "gemini-3.5-flash-lite"
    return settings.GROQ_MODEL


def active_provider() -> str:
    """The configured provider name ("gemini" or "groq")."""
    return settings.AI_PROVIDER


def display_name() -> str:
    """A clean, human-readable label for the active provider + model.

    Derived from the actual backend configuration — never hardcoded in the UI.
    Examples: "Gemini 3.5 Flash (Gemini)" or "llama-3.3-70b-versatile (Groq)".
    """
    if settings.AI_PROVIDER == "gemini":
        model = settings.AI_MODEL or "gemini-3.5-flash-lite"
        pretty = " ".join(part.capitalize() for part in model.split("-"))
        return f"{pretty} (Gemini)"
    return f"{settings.GROQ_MODEL} (Groq)"


def _groq_client() -> Any:
    """Build the Groq client via ``app.services.ai_service.Groq``.

    Resolved at call time so tests that patch ``app.services.ai_service.Groq``
    keep intercepting the call.
    """
    from app.services import ai_service

    return ai_service.Groq(api_key=settings.GROQ_API_KEY)


def _gemini_client() -> Any:
    """Build the Gemini client with the official google-genai SDK."""
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _groq_messages(
    system: Optional[str], messages: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    if system:
        return [{"role": "system", "content": system}, *messages]
    return list(messages)


def _gemini_contents(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Convert {role, content} messages to Gemini Content parts."""
    contents = [
        {
            "role": "model" if message.get("role") == "assistant" else "user",
            "parts": [{"text": message.get("content", "")}],
        }
        for message in messages
    ]
    if not contents:
        contents = [{"role": "user", "parts": [{"text": ""}]}]
    return contents


def _groq_complete(
    system: Optional[str],
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    json_mode: bool = False,
) -> str:
    client = _groq_client()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=_groq_messages(system, messages),
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    )
    return response.choices[0].message.content


def _gemini_complete(
    system: Optional[str],
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    json_mode: bool = False,
) -> str:
    from google.genai import types

    client = _gemini_client()
    config_kwargs = {
        "system_instruction": system,
        "max_output_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    response = client.models.generate_content(
        model=settings.AI_MODEL,
        contents=_gemini_contents(messages),
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return getattr(response, "text", None)


def _normalize_groq_error(exc: Exception) -> AIProviderError:
    import groq

    auth_error = getattr(groq, "AuthenticationError", None)
    rate_error = getattr(groq, "RateLimitError", None)
    conn_error = getattr(groq, "APIConnectionError", None)
    status_error = getattr(groq, "APIStatusError", None)

    if auth_error and isinstance(exc, auth_error):
        return AIProviderError(
            "The AI API key is invalid or was rejected. Check GROQ_API_KEY in backend/.env."
        )
    if rate_error and isinstance(exc, rate_error):
        return AIProviderError(
            "The AI service is rate-limited right now. Please wait a moment and try again."
        )
    if conn_error and isinstance(exc, conn_error):
        return AIProviderError(
            "Couldn't reach the AI service. Check your internet connection and try again."
        )
    if status_error and isinstance(exc, status_error):
        return AIProviderError("The AI service returned an error. Please try again in a moment.")
    return AIProviderError(
        "I couldn't process that request because of an unexpected AI service error. Please try again."
    )


def _normalize_gemini_error(exc: Exception) -> AIProviderError:
    name = type(exc).__name__.lower()
    text = str(exc).lower()

    if "auth" in name or "invalid" in name or "permission" in name or "key" in text:
        return AIProviderError(
            "The AI API key is invalid or was rejected. Check GEMINI_API_KEY in backend/.env."
        )
    if "429" in text or "rate" in text or "quota" in text or "resource_exhausted" in name:
        return AIProviderError(
            "The AI service is rate-limited right now. Please wait a moment and try again."
        )
    if "connect" in text or "dns" in text or "network" in text or "timeout" in text:
        return AIProviderError(
            "Couldn't reach the AI service. Check your internet connection and try again."
        )
    return AIProviderError("The AI service returned an error. Please try again in a moment.")


def _normalize_provider_error(provider: str, exc: Exception) -> AIProviderError:
    if provider == "gemini":
        return _normalize_gemini_error(exc)
    return _normalize_groq_error(exc)


def complete_text(
    *,
    system: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    json_mode: bool = False,
) -> str:
    """Return the raw text from the active provider.

    Raises ``AIProviderError`` with a safe user-facing message when the
    provider fails. Empty/malformed output is returned as-is so callers keep
    their existing validation. ``json_mode`` asks the provider for strict JSON
    output (Gemini response_mime_type / Groq response_format json_object).
    """
    messages = messages or []
    provider = settings.AI_PROVIDER
    try:
        if provider == "gemini":
            return _gemini_complete(system, messages, max_tokens, temperature, json_mode)
        return _groq_complete(system, messages, max_tokens, temperature, json_mode)
    except AIProviderError:
        raise
    except Exception as exc:
        logger.warning("AI provider '%s' failed: %s", provider, exc)
        raise _normalize_provider_error(provider, exc) from exc
import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _ai_provider_groq(monkeypatch):
    """Force the Groq provider for the whole test suite.

    The production default is Gemini (``AI_PROVIDER=gemini``), but the existing
    test surface mocks ``app.services.ai_service.Groq``. Pinning the Groq path
    with a fake key keeps every existing test hermetic (no real AI calls) and
    makes Gemini tests opt in explicitly via their own fixtures.
    """
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test-for-tests")
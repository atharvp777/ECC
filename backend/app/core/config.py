from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Orbit"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    DATABASE_URL: str = f"sqlite:///{Path(__file__).resolve().parents[3]}/ecc.db"

    # AI provider — "gemini" (gemini-3.5-flash-lite) or "groq" (llama-3.3-70b).
    # Gemini is the primary provider; Groq stays as a fallback.
    AI_PROVIDER: str = "gemini"
    AI_MODEL: str = "gemini-3.5-flash-lite"

    # Google Gemini — primary AI provider
    GEMINI_API_KEY: str = ""

    # Groq — free API, replaces OpenAI for all chat + summarization
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # OpenAI — only needed for Whisper audio transcription (optional)
    OPENAI_API_KEY: str = ""

    # Google Calendar OAuth2
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/integrations/google/callback"

    UPLOADS_DIR: Path = Path(__file__).resolve().parents[3] / "uploads"
    KNOWLEDGE_DIR: Path = Path(__file__).resolve().parents[3] / "knowledge"

    class Config:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        env_file_encoding = "utf-8"

    @property
    def is_configured(self) -> bool:
        """Return True if the minimal set of credentials needed for core features are present."""
        # Core features that must not be empty for the API to start serving requests
        required = {
            "APP_NAME",
            "DATABASE_URL",
            "GROQ_MODEL",
        }
        return all(getattr(self, name) for name in required)


settings = Settings()

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

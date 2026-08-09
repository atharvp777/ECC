from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    APP_NAME: str = "Engineering Command Center"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/ecc.db"

    # Groq — free API, replaces OpenAI for all chat + summarization
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # OpenAI — only needed for Whisper audio transcription (optional)
    OPENAI_API_KEY: str = ""

    # Google Calendar OAuth2
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/integrations/google/callback"

    # GitHub
    GITHUB_PAT: str = ""
    GITHUB_USERNAME: str = ""

    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    KNOWLEDGE_DIR: Path = BASE_DIR / "knowledge"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"


settings = Settings()

settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

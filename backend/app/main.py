from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base

# Import models so SQLAlchemy can discover them for table creation
import app.models  # noqa: F401

from app.routers import (
    projects,
    tasks,
    notes,
    documents,
    meetings,
    dashboard,
    chat,
    knowledge,
    integrations,
    meeting_intelligence,
    tools,
)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for the Engineering Command Center.",
)

# CORS
#
# The application can run from:
# - Vite development server
# - Tauri desktop WebView
# - localhost / 127.0.0.1
#
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(notes.router)
app.include_router(documents.router)
app.include_router(meetings.router)
app.include_router(dashboard.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(integrations.router)
app.include_router(meeting_intelligence.router)
app.include_router(tools.router)


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.migrations import run_idempotent_migrations

# Import models so SQLAlchemy can discover them for table creation
import app.models  # noqa: F401

from app.routers import (
    projects,
    tasks,
    notes,
    documents,
    dashboard,
    planning,
    chat,
    knowledge,
    integrations,
    tools,
)

# Create database tables
Base.metadata.create_all(bind=engine)

# Add columns introduced after the first release (safe to run repeatedly)
run_idempotent_migrations(engine)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for Orbit.",
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
app.include_router(dashboard.router)
app.include_router(planning.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(integrations.router)
app.include_router(tools.router)


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }

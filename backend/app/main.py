from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base

# Import models so SQLAlchemy can discover them for table creation
import app.models  # noqa: F401

from app.routers import projects, tasks, notes, documents, meetings, dashboard, chat, knowledge, integrations, meeting_intelligence

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for the Engineering Command Center — Atharv's personal AI-powered productivity system.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(notes.router)
app.include_router(documents.router)
app.include_router(meetings.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(integrations.router)
app.include_router(meeting_intelligence.router)


@app.get("/", tags=["health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}

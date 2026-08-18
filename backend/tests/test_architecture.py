"""Architecture cleanup tests.

The Engineering Command Center model is:

    Category → Project → (Tasks, Documents)
    Task → optional Google Calendar event  (task_type: work | reminder | meeting)
    AI Chat = the natural-language interface.

Meetings are Tasks (task_type=meeting). GitHub is removed. Documents live
under Projects (no separate Documents/Meetings sidebar modules). Categories
are exactly Personal, Baja, JobPrep, College, Study Abroad.

These tests assert the new architecture holds (Google Calendar and Gemini are
mocked — no real external writes).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services import google_calendar
from app.services.ai_service import chat_with_ai
from app.services.tools import (
    create_project as create_project_tool,
    create_task as create_task_tool,
    CreateProjectRequest,
    CreateTaskRequest,
)
from app.models import Task
from app.models.project import Project, ProjectCategory
from app.models.task import TaskType

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


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


# ----------------------------------------------------------------------
# Categories: exactly Personal, Baja, JobPrep, College, Study Abroad
# ----------------------------------------------------------------------
def test_project_categories_are_the_five_allowed():
    assert {c.value for c in ProjectCategory} == {
        "personal", "baja", "jobprep", "college", "studyabroad",
    }


@pytest.mark.parametrize(
    "category",
    ["personal", "baja", "jobprep", "college", "studyabroad"],
)
def test_create_project_accepts_each_category(db_session, category):
    result = create_project_tool(db_session, CreateProjectRequest(name=f"Proj {category}", category=category))
    project = result["data"]
    assert project.category.value == category


def test_create_project_rejects_invalid_category(db_session):
    from app.services.tool_dispatcher import execute_tool

    result = execute_tool("create_project", {"name": "Bad", "category": "agrovault"}, db_session)
    assert "error" in result["data"]
    assert "Invalid project category" in result["data"]["error"]


def test_create_project_defaults_to_personal(db_session):
    result = create_project_tool(db_session, CreateProjectRequest(name="Defaulted"))
    assert result["data"].category == ProjectCategory.PERSONAL


# ----------------------------------------------------------------------
# Meetings are tasks (task_type=meeting)
# ----------------------------------------------------------------------
def test_meeting_with_time_creates_task_and_calendar_event(db_session):
    created = {"id": "evt_meet_1", "summary": "Meeting with Prof X", "status": "confirmed"}
    with patch.object(google_calendar, "create_calendar_event", return_value=created) as mock_create:
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Meeting with Prof X",
            priority="medium",
            task_type="meeting",
            when="tomorrow",
            start_time="16:00",
            duration_minutes=60,
            schedule_on_calendar=True,
        ))

    task = result["data"]
    assert task.task_type == TaskType.MEETING
    assert task.google_calendar_event_id == "evt_meet_1"
    assert task.calendar_sync_error is None
    assert task.scheduled_start is not None
    assert task.scheduled_end is not None
    mock_create.assert_called_once()


def test_meeting_reminder_creates_task_without_calendar_event(db_session):
    # No date/time given → a meeting task is created but no calendar event is
    # ever invented (the server asks for a time instead).
    result = create_task_tool(db_session, CreateTaskRequest(
        title="Meeting with Prof X",
        priority="medium",
        task_type="meeting",
        when=None,
        schedule_on_calendar=False,
    ))

    task = result["data"]
    assert task.task_type == TaskType.MEETING
    assert task.google_calendar_event_id is None
    assert task.scheduled_start is None
    assert task.scheduled_end is None


def test_meeting_with_time_via_chat_creates_task_and_event(db_session):
    """Chat-level: 'schedule a meeting … tomorrow at 4 PM' → task + Google event."""
    planner_payload = {
        "tool": "create_task",
        "args": {
            "title": "Meeting with Prof X",
            "priority": "MEDIUM",
            "task_type": "meeting",
            "deadline": None,
            "project_name": None,
            "when": "tomorrow",
            "start_time": "16:00",
            "duration_minutes": 60,
            "schedule_on_calendar": True,
        },
    }
    created = {"id": "evt_chat_meet", "summary": "Meeting with Prof X", "status": "confirmed"}
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(json.dumps(planner_payload))
        mock_groq.return_value = mock_client

        with patch.object(google_calendar, "create_calendar_event", return_value=created):
            reply = chat_with_ai(
                [{"role": "user", "content": "Schedule a meeting with Prof X tomorrow at 4 PM"}],
                db_session,
            )

    assert "Created task" in reply
    assert "added it to your Google Calendar" in reply
    task = db_session.query(Task).filter(Task.title == "Meeting with Prof X").first()
    assert task is not None
    assert task.task_type == TaskType.MEETING
    assert task.google_calendar_event_id == "evt_chat_meet"


# ----------------------------------------------------------------------
# Task ↔ Google Calendar behaviors preserved (regressions locked)
# ----------------------------------------------------------------------
def test_deadline_only_task_creates_no_event(db_session):
    with patch.object(google_calendar, "create_calendar_event") as mock_create:
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Submit report",
            priority="medium",
            deadline_when="Friday",
            schedule_on_calendar=False,
        ))

    task = result["data"]
    assert task.deadline is not None
    assert task.google_calendar_event_id is None
    mock_create.assert_not_called()


def test_scheduled_task_creates_event(db_session):
    created = {"id": "evt_sched", "summary": "Work on wiring", "status": "confirmed"}
    with patch.object(google_calendar, "create_calendar_event", return_value=created):
        result = create_task_tool(db_session, CreateTaskRequest(
            title="Work on wiring",
            priority="medium",
            when="tomorrow",
            start_time="10:00",
            duration_minutes=90,
            schedule_on_calendar=True,
        ))

    task = result["data"]
    assert task.google_calendar_event_id == "evt_sched"
    assert task.scheduled_start is not None
    assert (task.scheduled_end - task.scheduled_start).total_seconds() == 90 * 60


# ----------------------------------------------------------------------
# Frontend architecture (static source checks)
# ----------------------------------------------------------------------
def _read_frontend(relative):
    return (FRONTEND_DIR / relative).read_text(encoding="utf-8")


def test_sidebar_has_no_documents_or_meetings():
    sidebar = _read_frontend("components/Sidebar.jsx")
    for expected in ("Dashboard", "Projects", "Tasks", "AI Chat", "Integrations", "Settings"):
        assert expected in sidebar
    assert "Documents" not in sidebar
    assert "Meetings" not in sidebar


def test_app_routes_have_no_meetings():
    app_jsx = _read_frontend("App.jsx")
    assert "/meetings" not in app_jsx


def test_integrations_page_has_no_github():
    integrations = _read_frontend("pages/Integrations.jsx")
    assert "GitHub" not in integrations
    assert "github" not in integrations.lower()
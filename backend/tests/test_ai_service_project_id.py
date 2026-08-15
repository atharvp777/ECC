import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.services.ai_service import _build_context, plan_tool_call
from app.models.project import Project
from app.models.task import Task
from app.core.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def db_session():
    """Create an in‑memory SQLite DB with a single active project."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    # Create a project with a known ID (will be 1)
    p = Project(name="BAJA HV", category="BAJA", status="ACTIVE")
    db.add(p)
    db.commit()
    # Create a task linked to that project
    task = Task(
        title="Design chassis",
        deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
        priority="HIGH",
        project_id=p.id,
    )
    db.add(task)
    db.commit()
    return db


def test_build_context_includes_project_id(db_session):
    """The live context must expose each active project's numeric ID."""
    ctx = _build_context(db_session)
    # The context should contain "(project_id=1)" for the project we created
    assert "(project_id=1)" in ctx
    # Also verify the project name appears
    assert "BAJA HV" in ctx


def test_plan_tool_call_resolves_project_id(db_session):
    """When a project name is mentioned, the planner must return its DB ID."""
    ctx = _build_context(db_session)

    fake_tool_call = {
        "tool": "create_task",
        "args": {
            "title": "Check battery wiring",
            "priority": "MEDIUM",
            "deadline": None,
            "project_id": 1,
        },
    }
    fake_response = MagicMock()
    fake_choices = [MagicMock()]
    fake_choices[0].message = MagicMock()
    fake_choices[0].message.content = json.dumps(fake_tool_call)
    fake_response.choices = fake_choices
    fake_response.choices[0].message = MagicMock()
    fake_response.choices[0].message.content = fake_choices[0].message.content

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = fake_response
        mock_groq.return_value = mock_instance

        result = plan_tool_call("Create a task called Check battery wiring in BAJA HV", ctx)

        # The function now returns the parsed dict directly
        assert result["tool"] == "create_task"
        assert result["args"]["project_id"] == 1


def test_plan_tool_call_no_project_uses_null(db_session):
    """If the user does not mention a project, project_id should be null."""
    ctx = _build_context(db_session)

    fake_tool_call = {
        "tool": "create_task",
        "args": {
            "title": "Write report",
            "priority": "MEDIUM",
            "deadline": None,
            "project_id": None,
        },
    }
    fake_response = MagicMock()
    fake_choices = [MagicMock()]
    fake_choices[0].message = MagicMock()
    fake_choices[0].message.content = json.dumps(fake_tool_call)
    fake_response.choices = fake_choices
    fake_response.choices[0].message = MagicMock()
    fake_response.choices[0].message.content = fake_choices[0].message.content

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = fake_response
        mock_groq.return_value = mock_instance

        result = plan_tool_call("Create a task called Write report", ctx)

        assert result["args"]["project_id"] is None


def test_plan_tool_call_unknown_project_uses_null(db_session):
    """Mentioning a non‑existent project must not invent an ID."""
    # Create a context that only contains the known project (BAJA HV)
    ctx = _build_context(db_session)

    fake_tool_call = {
        "tool": "create_task",
        "args": {
            "title": "Random task",
            "priority": "MEDIUM",
            "deadline": None,
            "project_id": None,
        },
    }
    fake_response = MagicMock()
    fake_choices = [MagicMock()]
    fake_choices[0].message = MagicMock()
    fake_choices[0].message.content = json.dumps(fake_tool_call)
    fake_response.choices = fake_choices
    fake_response.choices[0].message = MagicMock()
    fake_response.choices[0].message.content = fake_choices[0].message.content

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = fake_response
        mock_groq.return_value = mock_instance

        user_msg = "Add a task called Random task to UnknownProject"
        result = plan_tool_call(user_msg, ctx)

        assert result["args"]["project_id"] is None


def test_create_task_handles_deadline_none(db_session):
    """Creating a task without an explicit deadline should store deadline=None."""
    # Setup a temporary in‑memory DB with one active project
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    proj = db.query(Project).filter(Project.status == "ACTIVE").first()
    if not proj:
        proj = Project(name="TestProj", category="PERSONAL", status="ACTIVE")
        db.add(proj)
        db.commit()
    # Prepare args for create_task with deadline=None
    args = {
        "title": "Review specification",
        "priority": "MEDIUM",
        "deadline": None,
        "project_id": proj.id,
    }
    # Execute the tool directly (bypassing the AI layer)
    from app.services.tool_dispatcher import execute_tool
    result = execute_tool("create_task", args, db)
    # The dispatcher returns {"data": task} where `task` is a SQLAlchemy model
    assert result["data"].deadline is None

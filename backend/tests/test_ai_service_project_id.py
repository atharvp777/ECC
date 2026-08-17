import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.services.ai_service import _build_context, plan_tool_call
from app.models.project import Project
from app.models.task import Task
from app.models.project import ProjectCategory
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
    assert "ID: 1" in ctx
    assert "BAJA HV" in ctx


def test_build_context_includes_task_ids(db_session):
    """Task listings must expose IDs so the planner can target tasks by ID
    (enables update_task / complete_task from natural language)."""
    ctx = _build_context(db_session)
    assert "ID: 1" in ctx
    assert "Design chassis" in ctx


def test_plan_tool_call_resolves_project_id(db_session):
    """The planner should surface project_name, not invent project IDs."""
    ctx = _build_context(db_session)

    fake_tool_call = {
        "tool": "create_task",
        "args": {
            "title": "Check battery wiring",
            "priority": "MEDIUM",
            "deadline": None,
            "project_name": "BAJA HV",
        },
    }
    fake_response = MagicMock()
    fake_choices = [MagicMock()]
    fake_choices[0].message.content = json.dumps(fake_tool_call)
    fake_response.choices = fake_choices

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = fake_response
        mock_groq.return_value = mock_instance

        result = plan_tool_call("Create a task called Check battery wiring in BAJA HV", ctx)

        # The function now returns the parsed dict directly
        assert result["tool"] == "create_task"
        assert result["args"]["project_name"] == "BAJA HV"


def test_plan_tool_call_no_project_uses_null(db_session):
    """If the user does not mention a project, project_name should be null."""
    ctx = _build_context(db_session)

    fake_tool_call = {
            "tool": "create_task",
            "args": {
                "title": "Write report",
                "priority": "MEDIUM",
                "deadline": None,
                "project_name": None,
            },
        }
    fake_response = MagicMock()
    fake_choices = [MagicMock()]
    fake_choices[0].message = MagicMock()
    fake_choices[0].message.content = json.dumps(fake_tool_call)
    fake_response.choices = fake_choices

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = fake_response
        mock_groq.return_value = mock_instance

        result = plan_tool_call("Create a task called Write report", ctx)

        assert result["args"]["project_name"] is None


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
            "project_name": None,
        },
    }
    fake_response = MagicMock()
    fake_choices = [MagicMock()]
    fake_choices[0].message = MagicMock()
    fake_choices[0].message.content = json.dumps(fake_tool_call)
    fake_response.choices = fake_choices

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = fake_response
        mock_groq.return_value = mock_instance

        user_msg = "Add a task called Random task to UnknownProject"
        result = plan_tool_call(user_msg, ctx)

        assert result["args"]["project_name"] is None


def test_execute_tool_resolves_project_name_to_project_id(db_session):
    """The dispatcher must resolve project_name to the correct project_id."""
    from app.services.tool_dispatcher import execute_tool

    dmat = Project(name="dMAT", category="personal", status="ACTIVE")
    db_session.add(dmat)
    db_session.commit()
    db_session.refresh(dmat)

    result = execute_tool(
        "create_task",
        {
            "title": "Test battery wiring",
            "priority": "MEDIUM",
            "deadline": None,
            "project_name": "dmat",
        },
        db_session,
    )

    assert result["data"].project_id == dmat.id


def test_execute_tool_prefers_exact_case_match(db_session):
    """Exact project-name matches should win when case variants both exist."""
    from app.services.tool_dispatcher import execute_tool

    lower = Project(name="dmat", category="personal", status="ACTIVE")
    upper = Project(name="dMAT", category="personal", status="ACTIVE")
    db_session.add_all([lower, upper])
    db_session.commit()
    db_session.refresh(lower)
    db_session.refresh(upper)

    result = execute_tool(
        "create_task",
        {
            "title": "Case sensitive project task",
            "priority": "MEDIUM",
            "deadline": None,
            "project_name": "dMAT",
        },
        db_session,
    )

    assert result["data"].project_id == upper.id


def test_execute_tool_accepts_valid_direct_project_id(db_session):
    """Direct task tool calls with a valid project_id should still work."""
    from app.services.tool_dispatcher import execute_tool

    project = Project(name="Demo 1", category="personal", status="ACTIVE")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    result = execute_tool(
        "create_task",
        {
            "title": "Direct project id task",
            "priority": "MEDIUM",
            "deadline": None,
            "project_id": project.id,
        },
        db_session,
    )

    assert result["data"].project_id == project.id


def test_execute_tool_rejects_invalid_project_id(db_session):
    """Invalid project ids must not silently attach tasks to the wrong project."""
    from app.services.tool_dispatcher import execute_tool

    result = execute_tool(
        "create_task",
        {
            "title": "Bad project id task",
            "priority": "MEDIUM",
            "deadline": None,
            "project_id": 9999,
        },
        db_session,
    )

    assert "error" in result["data"]
    assert "Project not found" in result["data"]["error"]


def test_execute_tool_create_project_defaults_to_personal(db_session):
    """Natural-language project creation should default to the legitimate category."""
    from app.services.tool_dispatcher import execute_tool

    result = execute_tool(
        "create_project",
        {
            "name": "Robotics",
        },
        db_session,
    )

    assert result["data"].name == "Robotics"
    assert result["data"].category == ProjectCategory.PERSONAL


def test_execute_tool_create_project_rejects_invalid_category(db_session):
    """Invalid categories must fail before they reach the database."""
    from app.services.tool_dispatcher import execute_tool

    result = execute_tool(
        "create_project",
        {
            "name": "Bad Project",
            "category": "string",
        },
        db_session,
    )

    assert "error" in result["data"]
    assert "Invalid project category" in result["data"]["error"]


def test_execute_tool_rejects_unknown_project_name(db_session):
    """Unknown project names must fail instead of silently falling back."""
    from app.services.tool_dispatcher import execute_tool

    result = execute_tool(
        "create_task",
        {
            "title": "Test battery wiring",
            "priority": "MEDIUM",
            "deadline": None,
            "project_name": "does-not-exist",
        },
        db_session,
    )

    assert "error" in result["data"]
    assert "Project not found" in result["data"]["error"]


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

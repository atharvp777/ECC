import pytest
from datetime import datetime, timezone

from app.core.database import Base, SessionLocal
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskStatus, TaskPriority
from app.services.tools import (
    list_projects,
    create_project,
    update_project,
    list_tasks,
    create_task,
    update_task,
    complete_task,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# ----------------------------------------------------------------------
# Helper: create a fresh in‑memory DB and session for each test
# ----------------------------------------------------------------------
@pytest.fixture
def db_session():
    # Create a new in‑memory engine
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session: Session = TestSession()
    yield session
    session.close()
    test_engine.dispose()


# ----------------------------------------------------------------------
# LIST_PROJECTS / CREATE_PROJECT / UPDATE_PROJECT
# ----------------------------------------------------------------------
def test_list_projects(db_session: Session):
    # No projects yet – should return empty list
    result = list_projects(db_session, type("Req", (), {})())
    assert isinstance(result.get("data"), list)
    assert len(result["data"]) == 0

    # Create a project
    req = type("Req", (), {"name": "TestProj", "category": "personal"})()
    created = create_project(db_session, req)
    assert created["data"].name == "TestProj"

    # List again – should contain the new project
    projects = list_projects(db_session, type("Req", (), {})())
    assert any(p.name == "TestProj" for p in projects["data"])


def test_create_and_update_project(db_session: Session):
    # Create
    req = type("Req", (), {"name": "NewProj", "category": "baja"})()
    created = create_project(db_session, req)
    assert created["data"].name == "NewProj"
    proj_id = created["data"].id

    # Update
    upd_req = type("Req", (), {"project_id": proj_id, "name": "RenamedProj"})()
    updated = update_project(db_session, upd_req)
    assert updated["data"].name == "RenamedProj"

    # Verify update persisted
    refreshed = db_session.query(Project).filter(Project.id == proj_id).first()
    assert refreshed.name == "RenamedProj"


# ----------------------------------------------------------------------
# LIST_TASKS / CREATE_TASK / UPDATE_TASK / COMPLETE_TASK
# ----------------------------------------------------------------------
def test_list_tasks(db_session: Session):
    # No tasks – empty list
    result = list_tasks(db_session, type("Req", (), {})())
    assert isinstance(result.get("data"), list)
    assert len(result["data"]) == 0

    # Create a project to associate a task with
    proj = Project(name="TaskProj", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    # Create a task via the tool
    task_req = type("Req", (), {
        "title": "SampleTask",
        "priority": "MEDIUM",
        "deadline": "2025-01-01T00:00:00",
        "project_id": proj.id,
    })()
    created = create_task(db_session, task_req)
    task_id = created["data"].id

    # List tasks – should now contain the new one
    tasks = list_tasks(db_session, type("Req", (), {})())
    assert any(t.id == task_id for t in tasks["data"])


def test_create_task_with_datetime_deadline(db_session: Session):
    """Verify that a Python datetime can be passed as deadline and is stored correctly."""
    from datetime import datetime, timezone

    # Convert a Python datetime to ISO string (the format expected by the API)
    iso_deadline = datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc).isoformat()

    task_req = type("Req", (), {
        "title": "Wiring Diagram",
        "priority": "MEDIUM",
        "deadline": iso_deadline,
        "project_id": 1,  # assume project with id=1 exists or will be created
    })()

    # Ensure a project exists for the FK
    proj = Project(name="BajaProject", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    created = create_task(db_session, task_req)
    assert created["data"].title == "Wiring Diagram"
    # The deadline should be stored as a datetime object in the DB
    assert created["data"].deadline == datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc)


def test_update_task_and_complete_task(db_session: Session):
    # Setup a project and a task
    proj = Project(name="UpdateProj", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    task_req = type("Req", (), {
        "title": "UpdateTask",
        "priority": "HIGH",
        "deadline": "2025-12-31T23:59:59",
        "project_id": proj.id,
    })()
    created = create_task(db_session, task_req)
    task_id = created["data"].id

    # Update task status via tool
    upd_req = type("Req", (), {"task_id": task_id})()
    updated = update_task(db_session, upd_req)
    # The update function may not change anything here, but it should not error
    assert updated["data"] is not None

    # Complete the task
    complete_req = type("Req", (), {"task_id": task_id})()
    completed = complete_task(db_session, complete_req)
    assert completed["data"]["status"] == "DONE"  # assuming the response includes status


# ----------------------------------------------------------------------
# Helper to seed a minimal project for FK references
# ----------------------------------------------------------------------
@pytest.fixture
def seed_project(db_session: Session):
    proj = Project(name="TestProject", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)
    return proj.id

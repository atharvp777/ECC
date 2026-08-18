import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db, Base
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskPriority
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client, db
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _add_task(db, project_id, status=TaskStatus.TODO):
    task = Task(
        title="Task",
        priority=TaskPriority.MEDIUM,
        status=status,
        project_id=project_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_project_list_exposes_done_tasks_and_task_count(client):
    test_client, db = client

    p1 = Project(name="BAJA HV", category="baja", status="active")
    p2 = Project(name="dMAT", category="personal", status="active")
    db.add_all([p1, p2])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)

    _add_task(db, p1.id, TaskStatus.DONE)
    _add_task(db, p1.id, TaskStatus.IN_PROGRESS)
    _add_task(db, p2.id, TaskStatus.DONE)

    response = test_client.get("/projects/")

    assert response.status_code == 200
    by_name = {p["name"]: p for p in response.json()}

    assert by_name["BAJA HV"]["task_count"] == 2
    assert by_name["BAJA HV"]["done_tasks"] == 1
    assert by_name["dMAT"]["task_count"] == 1
    assert by_name["dMAT"]["done_tasks"] == 1


def test_project_list_zero_task_project_shows_zero_progress(client):
    test_client, db = client

    p = Project(name="Empty", category="personal", status="active")
    db.add(p)
    db.commit()

    response = test_client.get("/projects/")

    assert response.status_code == 200
    project = response.json()[0]
    assert project["task_count"] == 0
    assert project["done_tasks"] == 0


def test_project_list_preserves_existing_fields(client):
    test_client, db = client

    p = Project(name="Fields", category="college", status="active", color="#112233")
    db.add(p)
    db.commit()

    response = test_client.get("/projects/")

    assert response.status_code == 200
    project = response.json()[0]
    assert project["name"] == "Fields"
    assert project["category"] == "college"
    assert project["color"] == "#112233"
    assert "task_count" in project
    assert "done_tasks" in project
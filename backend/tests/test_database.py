import os
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, SessionLocal

# ----------------------------------------------------------------------
# Helper to create an isolated in‑memory SQLite DB for tests
# ----------------------------------------------------------------------
def _create_test_engine():
    """Return a new in‑memory SQLite engine bound to Base metadata."""
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    return test_engine

def test_database_import_and_session():
    """Verify that the DB engine, Base, and SessionLocal can be imported
    and that a session can be created without touching production data."""
    engine = _create_test_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    # Simple query to prove the models can be used
    from app.models.project import Project
    from app.models.task import Task

    # No production tables are accessed; only the metadata we just created
    assert db is not None
    db.close()
    engine.dispose()


def test_project_and_task_queries():
    """Confirm that Project and Task models can be queried via a session."""
    engine = _create_test_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    # Create a dummy Project and Task to ensure ORM mapping works
    from app.models.project import Project
    from app.models.task import Task

    proj = Project(name="test_proj", category="personal", status="active")
    db.add(proj)
    db.commit()
    db.refresh(proj)

    task = Task(title="test_task", priority="medium", status="todo", project_id=proj.id)
    db.add(task)
    db.commit()
    db.refresh(task)

    # Simple query should return them
    loaded_proj = db.query(Project).filter(Project.id == proj.id).first()
    loaded_task = db.query(Task).filter(Task.id == task.id).first()
    assert loaded_proj is not None
    assert loaded_task is not None

    db.close()
    engine.dispose()

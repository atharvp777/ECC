"""Enum canonicalization regression tests.

Architecture: AI/tool input → normalize to canonical domain value → validate
against enum → persist canonical value.

These prove that case variants of the same enum resolve to one canonical
value, that invalid values are rejected (never silently invented), that `WORK`
is a valid domain task type, and that the AI tool path can no longer persist
uppercase enum values.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.task import Task, TaskStatus, TaskPriority, TaskType
from app.models.project import Project, ProjectCategory, ProjectStatus
from app.services.tools import (
    _normalize_task_status,
    _normalize_task_priority,
    _normalize_task_type,
    _normalize_project_category,
    create_task,
    update_task,
    CreateTaskRequest,
    UpdateTaskRequest,
)
from app.services.tool_dispatcher import execute_tool


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
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
# Case variants resolve to ONE canonical member
# ----------------------------------------------------------------------

def test_status_case_variants_resolve_to_same_canonical():
    canonical = _normalize_task_status("DONE")
    assert canonical is TaskStatus.DONE
    assert _normalize_task_status("DONE") is canonical
    assert _normalize_task_status("Done") is canonical
    assert _normalize_task_status("done") is canonical
    assert _normalize_task_status("todo") is TaskStatus.TODO
    assert _normalize_task_status("IN_PROGRESS") is TaskStatus.IN_PROGRESS
    assert _normalize_task_status("Blocked") is TaskStatus.BLOCKED


def test_priority_case_variants_resolve_to_same_canonical():
    canonical = _normalize_task_priority("MEDIUM")
    assert canonical is TaskPriority.MEDIUM
    assert _normalize_task_priority("Medium") is canonical
    assert _normalize_task_priority("medium") is canonical
    assert _normalize_task_priority("HIGH") is TaskPriority.HIGH
    assert _normalize_task_priority("critical") is TaskPriority.CRITICAL
    assert _normalize_task_priority("low") is TaskPriority.LOW


def test_task_type_work_is_valid_domain_value():
    # WORK is a valid domain task type; its canonical value is "work".
    assert TaskType.WORK.value == "work"
    assert TaskType.WORK.name == "WORK"
    canonical = _normalize_task_type("WORK")
    assert canonical is TaskType.WORK
    assert _normalize_task_type("Work") is canonical
    assert _normalize_task_type("work") is canonical
    assert _normalize_task_type("meeting") is TaskType.MEETING
    assert _normalize_task_type("reminder") is TaskType.REMINDER


def test_project_category_case_variants_resolve_to_same_canonical():
    assert _normalize_project_category("BAJA") == "baja"
    assert _normalize_project_category("Baja") == "baja"
    assert _normalize_project_category("baja") == "baja"
    assert _normalize_project_category("PERSONAL") == "personal"


# ----------------------------------------------------------------------
# Invalid values are rejected, never silently invented
# ----------------------------------------------------------------------

def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        _normalize_task_status("shipped")
    with pytest.raises(ValueError):
        _normalize_task_status("completed")


def test_invalid_priority_rejected():
    with pytest.raises(ValueError):
        _normalize_task_priority("urgent")
    with pytest.raises(ValueError):
        _normalize_task_priority("top")


def test_invalid_task_type_rejected_not_defaulted_to_work():
    with pytest.raises(ValueError):
        _normalize_task_type("errand")
    with pytest.raises(ValueError):
        _normalize_task_type("appointment")


def test_invalid_project_category_rejected():
    with pytest.raises(ValueError):
        _normalize_project_category("work")


def test_direct_orm_assignment_of_name_now_rejected_by_enum():
    # The ORM persists canonical VALUES; assigning an enum NAME is rejected.
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import StatementError
    from app.core.database import Base as B

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    B.metadata.create_all(engine)
    s = Session(bind=engine)
    with pytest.raises(StatementError):
        s.add(Task(title="t", priority="MEDIUM", status="DONE"))
        s.commit()
    s.rollback()
    s.close()
    engine.dispose()


# ----------------------------------------------------------------------
# Persisted storage is the canonical lowercase value
# ----------------------------------------------------------------------

def test_create_task_persists_canonical_values(db_session):
    result = create_task(
        db_session,
        CreateTaskRequest(title="Probe", priority="MEDIUM", task_type="WORK", deadline_when="tomorrow"),
    )
    assert isinstance(result["data"], Task)
    task = result["data"]
    assert task.priority is TaskPriority.MEDIUM
    assert task.task_type is TaskType.WORK
    raw = db_session.execute(
        text("SELECT priority, task_type FROM tasks WHERE id=:i"), {"i": task.id}
    ).first()
    assert raw == ("medium", "work")


def test_update_task_persists_canonical_values(db_session):
    task = create_task(db_session, CreateTaskRequest(title="Probe"))["data"]
    assert isinstance(task, Task)
    result = update_task(
        db_session,
        UpdateTaskRequest(task_id=task.id, status="Done", priority="High"),
    )
    assert isinstance(result["data"], Task)
    raw = db_session.execute(
        text("SELECT status, priority FROM tasks WHERE id=:i"), {"i": task.id}
    ).first()
    assert raw == ("done", "high")


def test_execute_tool_cannot_reintroduce_uppercase(db_session):
    created = execute_tool(
        "create_task",
        {"title": "AI task", "priority": "MEDIUM", "task_type": "WORK"},
        db_session,
    )
    task = created["data"]
    raw = db_session.execute(
        text("SELECT priority, task_type, status FROM tasks WHERE id=:i"), {"i": task.id}
    ).first()
    assert raw == ("medium", "work", "todo")

    updated = execute_tool(
        "update_task",
        {"task_id": task.id, "status": "DONE", "priority": "CRITICAL"},
        db_session,
    )
    raw = db_session.execute(
        text("SELECT status, priority FROM tasks WHERE id=:i"), {"i": task.id}
    ).first()
    assert raw == ("done", "critical")


def test_execute_tool_rejects_invalid_values_without_mutation(db_session):
    bad = execute_tool(
        "create_task",
        {"title": "Bad", "priority": "urgent", "task_type": "WORK"},
        db_session,
    )
    assert "error" in bad["data"]
    assert db_session.query(Task).count() == 0

    ok = execute_tool("create_task", {"title": "Ok", "priority": "medium"}, db_session)["data"]
    bad_update = execute_tool(
        "update_task",
        {"task_id": ok.id, "status": "shipped"},
        db_session,
    )
    assert "error" in bad_update["data"]
    raw = db_session.execute(
        text("SELECT status FROM tasks WHERE id=:i"), {"i": ok.id}
    ).first()
    assert raw == ("todo",)


# ----------------------------------------------------------------------
# Existing valid lowercase values remain unchanged
# ----------------------------------------------------------------------

def test_lowercase_values_roundtrip_unchanged(db_session):
    task = Task(
        title="Stable",
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
        task_type=TaskType.WORK,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    raw = db_session.execute(text("SELECT status, priority, task_type FROM tasks")).first()
    assert raw == ("todo", "medium", "work")
    # And they compare correctly through the ORM layer.
    assert task.status is TaskStatus.TODO
    assert task.priority is TaskPriority.MEDIUM


def test_router_schema_rejects_uppercase(db_session):
    # Pydantic schema (API) path stays strict: values only, never names.
    from app.schemas.task import TaskCreate

    with pytest.raises(ValueError):
        TaskCreate(title="x", priority="MEDIUM")
    with pytest.raises(ValueError):
        TaskCreate(title="x", status="DONE")
    # The canonical value is accepted.
    parsed = TaskCreate(title="x", priority="medium", status="done")
    assert parsed.priority is TaskPriority.MEDIUM
    assert parsed.status is TaskStatus.DONE
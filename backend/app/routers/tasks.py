from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.models.task import Task, TaskStatus, TaskPriority
from app.schemas.task import TaskCreate, TaskUpdate, TaskRead

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _apply_filters(query, project_id, status_filter, priority_filter):
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if status_filter:
        query = query.filter(Task.status == status_filter)
    if priority_filter:
        query = query.filter(Task.priority == priority_filter)
    return query


@router.get("/", response_model=list[TaskRead])
def list_tasks(
    project_id: int | None = Query(None),
    status: TaskStatus | None = Query(None),
    priority: TaskPriority | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Task)
    query = _apply_filters(query, project_id, status, priority)
    return query.order_by(Task.deadline.asc().nullslast(), Task.created_at.desc()).all()


@router.get("/today", response_model=list[TaskRead])
def get_todays_tasks(db: Session = Depends(get_db)):
    """Returns tasks due today or overdue and not yet done."""
    now = datetime.now(timezone.utc)
    end_of_today = now.replace(hour=23, minute=59, second=59)
    tasks = (
        db.query(Task)
        .filter(
            Task.status != TaskStatus.DONE,
            Task.deadline <= end_of_today,
        )
        .order_by(Task.priority.asc(), Task.deadline.asc())
        .all()
    )
    return tasks


@router.get("/upcoming", response_model=list[TaskRead])
def get_upcoming_tasks(days: int = Query(7), db: Session = Depends(get_db)):
    """Returns tasks due in the next N days."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=days)
    tasks = (
        db.query(Task)
        .filter(
            Task.status != TaskStatus.DONE,
            Task.deadline >= now,
            Task.deadline <= future,
        )
        .order_by(Task.deadline.asc())
        .all()
    )
    return tasks


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = payload.model_dump(exclude_unset=True)

    # Auto-set completed_at when marking done
    if updates.get("status") == TaskStatus.DONE and task.status != TaskStatus.DONE:
        updates["completed_at"] = datetime.now(timezone.utc)
    elif updates.get("status") and updates["status"] != TaskStatus.DONE:
        updates["completed_at"] = None

    for field, value in updates.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()

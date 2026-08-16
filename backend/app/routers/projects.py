from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectRead, ProjectReadWithStats

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()

    total_counts = dict(
        db.query(Task.project_id, func.count(Task.id))
        .group_by(Task.project_id)
        .all()
    )
    done_counts = dict(
        db.query(Task.project_id, func.count(Task.id))
        .filter(Task.status == TaskStatus.DONE)
        .group_by(Task.project_id)
        .all()
    )

    result = []
    for p in projects:
        data = ProjectRead.model_validate(p)
        data.task_count = total_counts.get(p.id, 0)
        data.done_tasks = done_counts.get(p.id, 0)
        result.append(data)
    return result


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    data = ProjectRead.model_validate(project)
    data.task_count = 0
    return data


@router.get("/{project_id}", response_model=ProjectReadWithStats)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.now(timezone.utc)
    total = db.query(func.count(Task.id)).filter(Task.project_id == project_id).scalar() or 0
    done = (
        db.query(func.count(Task.id))
        .filter(Task.project_id == project_id, Task.status == TaskStatus.DONE)
        .scalar() or 0
    )
    overdue = (
        db.query(func.count(Task.id))
        .filter(
            Task.project_id == project_id,
            Task.deadline < now,
            Task.status != TaskStatus.DONE,
        )
        .scalar() or 0
    )

    data = ProjectReadWithStats.model_validate(project)
    data.total_tasks = total
    data.done_tasks = done
    data.overdue_tasks = overdue
    data.task_count = total
    return data


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    task_count = db.query(func.count(Task.id)).filter(Task.project_id == project_id).scalar()
    data = ProjectRead.model_validate(project)
    data.task_count = task_count or 0
    return data


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()

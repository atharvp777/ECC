from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.project import Project
from app.schemas.project_context import (
    ProjectContextCreate,
    ProjectContextUpdate,
    ProjectContextRead,
)
from app.services import project_context_service as svc

router = APIRouter(prefix="/projects", tags=["project-context"])


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("/{project_id}/context", response_model=list[ProjectContextRead])
def list_context(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return svc.list_project_context(db, project_id)


@router.post(
    "/{project_id}/context",
    response_model=ProjectContextRead,
    status_code=status.HTTP_201_CREATED,
)
def create_context(project_id: int, payload: ProjectContextCreate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return svc.create_project_context(
        db, project_id, payload.content, category=payload.category, source=payload.source
    )


@router.patch("/{project_id}/context/{context_id}", response_model=ProjectContextRead)
def update_context(
    project_id: int, context_id: int, payload: ProjectContextUpdate, db: Session = Depends(get_db)
):
    _get_project_or_404(db, project_id)
    item = svc.update_project_context(
        db, project_id, context_id, **payload.model_dump(exclude_unset=True)
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project context not found"
        )
    return item


@router.delete("/{project_id}/context/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_context(project_id: int, context_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    if not svc.delete_project_context(db, project_id, context_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project context not found"
        )
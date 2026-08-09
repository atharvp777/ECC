from pydantic import BaseModel
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models import Project, Task
from app.services.google_calendar import (
    get_upcoming_events as gc_get_upcoming_events,
    create_calendar_event as gc_create_calendar_event,
    update_calendar_event as gc_update_calendar_event,
    delete_calendar_event as gc_delete_calendar_event,
)


# ---------- Request schemas ----------
class ListProjectsRequest(BaseModel):
    pass


class CreateProjectRequest(BaseModel):
    name: str
    category: str = "Personal"


class UpdateProjectRequest(BaseModel):
    project_id: int
    name: Optional[str] = None
    category: Optional[str] = None


class ListTasksRequest(BaseModel):
    pass


class CreateTaskRequest(BaseModel):
    title: str
    priority: str
    deadline: str
    project_id: Optional[int] = None


class UpdateTaskRequest(BaseModel):
    task_id: int
    **kwargs  # allow any additional fields


class CompleteTaskRequest(BaseModel):
    task_id: int


class ListCalendarEventsRequest(BaseModel):
    pass


class CreateCalendarEventRequest(BaseModel):
    event_data: Dict[str, Any]


class UpdateCalendarEventRequest(BaseModel):
    event_id: str
    event_data: Dict[str, Any]


class DeleteCalendarEventRequest(BaseModel):
    event_id: str


# ---------- Wrapper implementations ----------
def list_projects(db: Session, _: ListProjectsRequest) -> Dict[str, Any]:
    projects = db.query(Project).filter(Project.status == "ACTIVE").all()
    return {"data": projects}


def create_project(db: Session, req: CreateProjectRequest) -> Dict[str, Any]:
    proj = Project(name=req.name, category=req.category, status="ACTIVE")
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return {"data": proj}


def update_project(db: Session, req: UpdateProjectRequest) -> Dict[str, Any]:
    proj = db.query(Project).filter(Project.id == req.project_id).first()
    if not proj:
        return {"data": None}
    if req.name:
        proj.name = req.name
    if req.category:
        proj.category = req.category
    db.commit()
    db.refresh(proj)
    return {"data": proj}


def list_tasks(db: Session, _: ListTasksRequest) -> Dict[str, Any]:
    tasks = db.query(Task).all()
    return {"data": tasks}


def create_task(db: Session, req: CreateTaskRequest) -> Dict[str, Any]:
    task = Task(
        title=req.title,
        priority=req.priority,
        deadline=req.deadline,
        project_id=req.project_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"data": task}


def update_task(db: Session, req: UpdateTaskRequest) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    for key, value in req.kwargs.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return {"data": task}


def complete_task(db: Session, req: CompleteTaskRequest) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        return {"data": None}
    task.status = "DONE"
    db.commit()
    db.refresh(task)
    return {"data": task}


def list_calendar_events(db: Session, _: ListCalendarEventsRequest) -> Dict[str, Any]:
    events = gc_get_upcoming_events(days=7, max_results=20)
    return {"data": events}


def create_calendar_event(db: Session, req: CreateCalendarEventRequest) -> Dict[str, Any]:
    event = gc_create_calendar_event(req.event_data)
    return {"data": event}


def update_calendar_event(db: Session, req: UpdateCalendarEventRequest) -> Dict[str, Any]:
    updated = gc_update_calendar_event(req.event_id, req.event_data)
    return {"data": updated}


def delete_calendar_event(db: Session, req: DeleteCalendarEventRequest) -> Dict[str, Any]:
    gc_delete_calendar_event(req.event_id)
    return {"data": {"status": "deleted", "event_id": req.event_id}}

from sqlalchemy.orm import Session
from typing import Dict, Any
from sqlalchemy import func
from app.models.project import Project
from app.services.tools import (
    list_projects as lp,
    create_project as cp,
    update_project as up,
    list_tasks as lt,
    create_task as ct,
    update_task as ut,
    complete_task as ct_complete,
    list_calendar_events as lce,
    create_calendar_event as cce,
    update_calendar_event as uce,
    delete_calendar_event as dce,
    add_task_to_calendar as atc,
    remove_task_from_calendar as rtc,
)
from datetime import datetime, timezone, timedelta

TOOL_FUNCTIONS: Dict[str, Any] = {
    "list_projects": lp,
    "create_project": cp,
    "update_project": up,
    "list_tasks": lt,
    "create_task": ct,
    "update_task": ut,
    "complete_task": ct_complete,
    "list_calendar_events": lce,
    "create_calendar_event": cce,
    "update_calendar_event": uce,
    "delete_calendar_event": dce,
    "add_task_to_calendar": atc,
    "remove_task_from_calendar": rtc,
}


def execute_tool(tool_name: str, args: dict, db: Session) -> Dict[str, Any]:
    """
    Dispatch a tool call.

    Tool wrapper functions expect their arguments inside a Pydantic
    request object, so build the appropriate request model here.
    """
    tool_func = TOOL_FUNCTIONS.get(tool_name)

    if not tool_func:
        return {"data": {"error": f"Unknown tool: {tool_name}"}}

    try:
        args = dict(args or {})

        if tool_name == "create_task":
            project_name = args.pop("project_name", None)
            if project_name is not None:
                if not isinstance(project_name, str) or not project_name.strip():
                    return {"data": {"error": "project_name must be a non-empty string"}}

                trimmed = project_name.strip()
                normalized = trimmed.lower()
                project = (
                    db.query(Project)
                    .filter(func.trim(Project.name) == trimmed)
                    .first()
                )

                if project is None:
                    matches = (
                        db.query(Project)
                        .filter(func.lower(func.trim(Project.name)) == normalized)
                        .all()
                    )
                    if len(matches) == 1:
                        project = matches[0]
                    elif len(matches) > 1:
                        return {"data": {"error": f'Ambiguous project name: "{project_name}"'}}

                if not project:
                    return {"data": {"error": f'Project not found: "{project_name}"'}}

                args["project_id"] = project.id

        if tool_name == "create_calendar_event":
            from app.services.tools import build_calendar_event_body
            args = {"event_data": build_calendar_event_body(args)}
        elif tool_name == "update_calendar_event":
            event_id = args.get("event_id")
            event_data = args.get("event_data")
            if event_id is None:
                return {"data": {"error": "update_calendar_event requires an event_id"}}
            if not isinstance(event_data, dict):
                from app.services.tools import build_calendar_event_body
                event_data = build_calendar_event_body(args)
            args = {"event_id": event_id, "event_data": event_data}

        from app.services.tools import (
            ListProjectsRequest,
            CreateProjectRequest,
            UpdateProjectRequest,
            ListTasksRequest,
            CreateTaskRequest,
            UpdateTaskRequest,
            CompleteTaskRequest,
            ListCalendarEventsRequest,
            CreateCalendarEventRequest,
            UpdateCalendarEventRequest,
            DeleteCalendarEventRequest,
            AddTaskToCalendarRequest,
            RemoveTaskFromCalendarRequest,
        )

        request_models = {
            "list_projects": ListProjectsRequest,
            "create_project": CreateProjectRequest,
            "update_project": UpdateProjectRequest,
            "list_tasks": ListTasksRequest,
            "create_task": CreateTaskRequest,
            "update_task": UpdateTaskRequest,
            "complete_task": CompleteTaskRequest,
            "list_calendar_events": ListCalendarEventsRequest,
            "create_calendar_event": CreateCalendarEventRequest,
            "update_calendar_event": UpdateCalendarEventRequest,
            "delete_calendar_event": DeleteCalendarEventRequest,
            "add_task_to_calendar": AddTaskToCalendarRequest,
            "remove_task_from_calendar": RemoveTaskFromCalendarRequest,
        }

        request_model = request_models.get(tool_name)

        if request_model is None:
            return {"data": {"error": f"No request model for tool: {tool_name}"}}

        request = request_model(**args)

        return tool_func(db, request)

    except Exception as exc:
        return {"data": {"error": str(exc)}}

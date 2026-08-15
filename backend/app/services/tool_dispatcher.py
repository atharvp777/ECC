from sqlalchemy.orm import Session
from typing import Dict, Any
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
}


def execute_tool(tool_name: str, args: dict, db: Session) -> Dict[str, Any]:
    """
    Dispatch a tool call.

    Tool wrapper functions expect their arguments inside a Pydantic
    request object, so build the appropriate request model here.
    """
    func = TOOL_FUNCTIONS.get(tool_name)

    if not func:
        return {"data": {"error": f"Unknown tool: {tool_name}"}}

    try:
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
        }

        request_model = request_models.get(tool_name)

        if request_model is None:
            return {"data": {"error": f"No request model for tool: {tool_name}"}}

        request = request_model(**args)

        return func(db, request)

    except Exception as exc:
        return {"data": {"error": str(exc)}}

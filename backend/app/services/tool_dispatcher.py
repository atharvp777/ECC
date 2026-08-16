from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
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
    SYSTEM_TIMEZONE,
)
from datetime import datetime, timezone, timedelta
import re

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


def _is_google_event_id_like(value: str) -> bool:
    """True when a value has the alphanumeric-slug shape of a Google event id.

    Google Calendar event ids never contain spaces. A task title (e.g.
    "QA scheduled task") is never a valid event id.
    """
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", value))


def execute_tool(
    tool_name: str,
    args: dict,
    db: Session,
    user_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Dispatch a tool call.

    Tool wrapper functions expect their arguments inside a Pydantic
    request object, so build the appropriate request model here.

    ``user_message`` is the user's ORIGINAL message when the tool was planned
    from natural language. For add_task_to_calendar / remove_task_from_calendar
    it is the authoritative task reference — the planner may choose the
    operation (and time) but must not paraphrase/generalize the task title.
    """
    tool_func = TOOL_FUNCTIONS.get(tool_name)

    if not tool_func:
        return {"data": {"error": f"Unknown tool: {tool_name}"}}

    try:
        args = dict(args or {})

        # ---- Task-calendar write defense (server-side) ---------------------
        # A raw calendar write must never be aimed at a task's linked event
        # with a fabricated event_id (e.g. a task title). When the event_id
        # matches a linked task, re-route through the task-calendar tools so
        # the task row stays in sync with Google. Values that cannot be a
        # Google event id are rejected before any Google call.
        if tool_name in ("update_calendar_event", "delete_calendar_event"):
            event_id = args.get("event_id")
            if not event_id or not isinstance(event_id, str) or not event_id.strip():
                return {"data": {"error": f"{tool_name} requires an event_id"}}

            from app.models.task import Task
            linked_task = (
                db.query(Task)
                .filter(Task.google_calendar_event_id == event_id)
                .first()
            )
            if linked_task is not None:
                if tool_name == "update_calendar_event":
                    tool_name = "add_task_to_calendar"
                    args = {
                        "task_id": linked_task.id,
                        "when": args.get("when"),
                        "start_time": args.get("start_time"),
                        "duration_minutes": args.get("duration_minutes", 60),
                        "timezone": args.get("timezone", SYSTEM_TIMEZONE),
                    }
                else:
                    tool_name = "remove_task_from_calendar"
                    args = {"task_id": linked_task.id}
            elif not _is_google_event_id_like(event_id):
                return {
                    "data": {
                        "error": (
                            f"'{event_id}' is not a known Google Calendar event id. "
                            "A task's calendar event is managed with the task tools."
                        )
                    }
                }
            # The re-route above changed tool_name; rebind the tool function so
            # the task-calendar tool actually runs.
            tool_func = TOOL_FUNCTIONS.get(tool_name)

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

        if tool_name in ("add_task_to_calendar", "remove_task_from_calendar"):
            from app.services.tools import resolve_task_for_calendar

            task_title = args.pop("task_title", None)
            task_id = args.get("task_id")

            # The user's ORIGINAL message is the authoritative task reference.
            # The planner may choose the operation and time, but it must not
            # paraphrase/generalize the task title, so resolve the message
            # verbatim. task_id is only used as a tie-breaker.
            reference = user_message if user_message else task_title

            if reference is not None:
                if not isinstance(reference, str) or not reference.strip():
                    return {"data": {"error": "task_title must be a non-empty string"}}
                resolution = resolve_task_for_calendar(
                    db,
                    reference,
                    task_id=task_id,
                    op="add" if tool_name == "add_task_to_calendar" else "remove",
                )
                if resolution["status"] != "found":
                    # Ambiguous / not found: never pick silently. No calendar
                    # write may happen until the user's intent is resolved.
                    return {
                        "data": {
                            "error": resolution["message"],
                            "reply_direct": True,
                            "candidates": [t.id for t in resolution.get("candidates", [])],
                        }
                    }
                args["task_id"] = resolution["task"].id
            elif task_id is None:
                return {"data": {"error": f"{tool_name} requires a task_title or a task_id"}}

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

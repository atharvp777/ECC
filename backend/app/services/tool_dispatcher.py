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
    Dispatches the requested tool name to the corresponding wrapper function.
    Returns the wrapper's output (expected to contain a ``data`` key).
    """
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return {"data": None}
    try:
        return func(db=db, **args)
    except Exception as exc:
        return {"data": {"error": str(exc)}}

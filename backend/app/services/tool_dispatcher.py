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
    bulk_update_tasks as but,
    delete_task as dt,
    list_calendar_events as lce,
    create_calendar_event as cce,
    update_calendar_event as uce,
    delete_calendar_event as dce,
    add_task_to_calendar as atc,
    remove_task_from_calendar as rtc,
    get_today_overview as gto,
    plan_my_day as pmd,
    estimate_task_effort as etf,
    apply_day_plan as adp,
    save_project_context as spc,
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
    "bulk_update_tasks": but,
    "delete_task": dt,
    "list_calendar_events": lce,
    "create_calendar_event": cce,
    "update_calendar_event": uce,
    "delete_calendar_event": dce,
    "add_task_to_calendar": atc,
    "remove_task_from_calendar": rtc,
    "get_today_overview": gto,
    "plan_my_day": pmd,
    "estimate_task_effort": etf,
    "apply_day_plan": adp,
    "save_project_context": spc,
}


# ----------------------------------------------------------------------
# save_project_context — server-side authorization gate
# ----------------------------------------------------------------------
# The planner is the primary router, but a mutation must never happen on an
# ambiguous or merely-implicit request. This deterministic guard confirms the
# user's ORIGINAL message expresses an explicit save/remember intent before any
# write is allowed. Questions and general requests ("what is X?", "explain Y",
# "make me a plan") never pass. Document/image text never reaches this layer —
# the planner only ever sees the user's own message text.
_SAVE_CONTEXT_QUESTION_STARTERS = (
    "what", "why", "how", "which", "who", "when", "where",
    "is ", "are ", "do ", "does ", "can ", "should ", "could ",
)
_SAVE_CONTEXT_STRONG_MARKERS = (
    "remember", "keep in mind", "note down", "note that", "store in",
    "save this", "save that", "save it", "save our", "save my",
    "save as project context", "save this as context", "as project context",
    "save the following", "remember this", "remember that", "remember our",
    "remember my",
)


def is_context_save_intent(text: str) -> bool:
    """True only for an EXPLICIT request to save durable project context.

    A bare "save"/"remember" is never enough on its own when it collides with
    task/reminder/estimate language; the marker list is deliberately explicit.
    """
    lower = (text or "").strip().lower()
    if not lower:
        return False
    if "?" in lower:
        return False
    if lower.startswith(_SAVE_CONTEXT_QUESTION_STARTERS):
        return False
    # Reminder/action wording must never be treated as a durable-fact save.
    if "remind" in lower or "reminder" in lower:
        return False
    return any(marker in lower for marker in _SAVE_CONTEXT_STRONG_MARKERS)


def _is_google_event_id_like(value: str) -> bool:
    """True when a value has the alphanumeric-slug shape of a Google event id.

    Google Calendar event ids never contain spaces. A task title (e.g.
    "QA scheduled task") is never a valid event id.
    """
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", value))


def _resolve_project_name(db: Session, project_name: str) -> tuple:
    """Resolve a user-provided project name to a project_id.

    Exact match wins, then a case-insensitive match (must be unambiguous).
    Returns ``(project_id, None)`` on success or ``(None, {"error": ...})``.
    """
    if not isinstance(project_name, str) or not project_name.strip():
        return None, {"error": "project_name must be a non-empty string"}

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
            return None, {"error": f'Ambiguous project name: "{project_name}"'}

    if not project:
        return None, {"error": f'Project not found: "{project_name}"'}

    return project.id, None


def execute_tool(
    tool_name: str,
    args: dict,
    db: Session,
    user_message: Optional[str] = None,
    last_assistant_reply: Optional[str] = None,
    explicit_authorization: bool = False,
    trusted_project_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Dispatch a tool call.

    Tool wrapper functions expect their arguments inside a Pydantic
    request object, so build the appropriate request model here.

    ``user_message`` is the user's ORIGINAL message when the tool was planned
    from natural language. For add_task_to_calendar / remove_task_from_calendar
    it is the authoritative task reference — the planner may choose the
    operation (and time) but must not paraphrase/generalize the task title.

    ``last_assistant_reply`` and ``explicit_authorization`` support the
    server-side authorization gate for apply_day_plan: the user's conversational
    message must explicitly authorize calendar writes (a /tool directive counts
    as explicit authorization).

    ``trusted_project_id`` is the authoritative project id from application
    context (the project-scoped AI workspace, or a deterministic conversation
    resolution) for the save_project_context tool. It is never derived from the
    model/planner: any project_id the model puts in ``args`` is discarded.
    """
    tool_func = TOOL_FUNCTIONS.get(tool_name)

    if not tool_func:
        return {"data": {"error": f"Unknown tool: {tool_name}"}}

    # ---- apply_day_plan: server-side authorization gate --------------------
    # Explicit user approval is enforced here, not only in the planner prompt.
    # A recommendation request, an ambiguous message, or a bare "okay" without
    # a prior confirmation question can never reach the calendar write path.
    if tool_name == "apply_day_plan":
        from app.services.day_plan_approval import is_scheduling_authorization

        authorized = explicit_authorization or is_scheduling_authorization(
            user_message or "", last_assistant_reply
        )
        if not authorized:
            return {
                "data": {
                    "error": (
                        "I'll add these blocks to your Google Calendar only "
                        "after you confirm. Do you want me to add this plan "
                        "to your Google Calendar?"
                    ),
                    "reply_direct": True,
                }
            }

    # ---- save_project_context: server-side authorization gate ---------------
    # A durable-context write happens ONLY when (a) the user's original message
    # expresses explicit save/remember intent (a /tool directive is inherently
    # explicit) and (b) a trusted project id exists from application context.
    # The model/planner can never authorize this write and never supplies the
    # project id.
    if tool_name == "save_project_context":
        from app.services.tools import SaveProjectContextRequest

        if user_message is not None and not is_context_save_intent(user_message):
            return {
                "data": {
                    "error": (
                        "I can't save that as project context — your message "
                        "doesn't look like an explicit request to remember it. "
                        "To save a durable fact, say something like "
                        '"Remember that we chose a microservices architecture."'
                    ),
                    "reply_direct": True,
                }
            }
        if trusted_project_id is None:
            return {
                "data": {
                    "error": (
                        "I couldn't determine which project to save this context "
                        "to. Open the project's AI workspace (or mention the "
                        "project explicitly) and try again."
                    ),
                    "reply_direct": True,
                }
            }
        # Never trust a model/planner-generated project_id. The trusted id from
        # application context is authoritative; a spoofed/mistaken id is dropped.
        try:
            args = dict(args or {})
            content = args["content"]
        except (KeyError, TypeError, ValueError):
            return {"data": {"error": "save_project_context requires a content string"}}
        if not isinstance(content, str) or not content.strip():
            return {"data": {"error": "save_project_context requires a non-empty content string"}}
        args = {
            "content": content,
            "project_id": trusted_project_id,
            "category": args.get("category"),
            "source": args.get("source"),
        }

        request = SaveProjectContextRequest(**args)
        return tool_func(db, request)

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
                project_id, err = _resolve_project_name(db, project_name)
                if err:
                    return {"data": err}
                args["project_id"] = project_id

        if tool_name == "bulk_update_tasks":
            project_name = args.pop("project_name", None)
            if project_name is not None:
                project_id, err = _resolve_project_name(db, project_name)
                if err:
                    return {"data": err}
                args["project_id"] = project_id

        if tool_name in (
            "add_task_to_calendar",
            "remove_task_from_calendar",
            "update_task",
            "complete_task",
            "delete_task",
            "estimate_task_effort",
        ):
            from app.services.tools import resolve_task_for_calendar

            op_map = {
                "add_task_to_calendar": "add",
                "remove_task_from_calendar": "remove",
                "update_task": "update",
                "complete_task": "complete",
                "delete_task": "delete",
                "estimate_task_effort": "estimate",
            }
            task_title = args.pop("task_title", None)
            task_id = args.get("task_id")

            # The user's ORIGINAL message is the authoritative task reference.
            # The planner may choose the operation and (for calendar tools) the
            # time, but it must not paraphrase/generalize the task title, so
            # resolve the message verbatim. task_id is only used as a tie-breaker.
            reference = user_message if user_message else task_title

            if reference is not None:
                if not isinstance(reference, str) or not reference.strip():
                    return {"data": {"error": "task_title must be a non-empty string"}}
                resolution = resolve_task_for_calendar(
                    db,
                    reference,
                    task_id=task_id,
                    op=op_map[tool_name],
                )
                if resolution["status"] != "found":
                    # A confirmation-style turn ("use that estimate") carries no
                    # task identity of its own; the planner copies the reference
                    # from the conversation. Resolve that only when the verbatim
                    # user message matched NOTHING — an ambiguous user message
                    # must still be surfaced for clarification and never be
                    # silently overridden by the planner's own title.
                    if (
                        resolution["status"] == "not_found"
                        and task_title
                        and isinstance(task_title, str)
                        and task_title.strip()
                        and reference != task_title
                    ):
                        alt = resolve_task_for_calendar(
                            db,
                            task_title,
                            task_id=task_id,
                            op=op_map[tool_name],
                        )
                        if alt["status"] == "found":
                            resolution = alt
                if resolution["status"] != "found":
                    # A reference with NO meaningful tokens (e.g. "task 5") is a
                    # bare-id mention — trust an explicit task_id the planner got
                    # from the live context. Any real ambiguity still clarifies.
                    if (
                        task_id is not None
                        and resolution["status"] == "not_found"
                        and not resolution.get("had_significant_tokens", True)
                    ):
                        args["task_id"] = task_id
                    else:
                        # Ambiguous / not found: never pick silently. No mutation
                        # may happen until the user's intent is resolved.
                        return {
                            "data": {
                                "error": resolution["message"],
                                "reply_direct": True,
                                "candidates": [
                                    t.id for t in resolution.get("candidates", [])
                                ],
                            }
                        }
                else:
                    args["task_id"] = resolution["task"].id
            elif task_id is None:
                if tool_name in ("add_task_to_calendar", "remove_task_from_calendar"):
                    return {"data": {"error": f"{tool_name} requires a task_title or a task_id"}}
                return {"data": {"error": f"{tool_name} requires a task_id or a task_title"}}

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
            BulkUpdateTasksRequest,
            DeleteTaskRequest,
            ListCalendarEventsRequest,
            CreateCalendarEventRequest,
            UpdateCalendarEventRequest,
            DeleteCalendarEventRequest,
            AddTaskToCalendarRequest,
            RemoveTaskFromCalendarRequest,
            GetTodayOverviewRequest,
            PlanMyDayRequest,
            EstimateTaskEffortRequest,
            ApplyDayPlanRequest,
            SaveProjectContextRequest,
        )

        request_models = {
            "list_projects": ListProjectsRequest,
            "create_project": CreateProjectRequest,
            "update_project": UpdateProjectRequest,
            "list_tasks": ListTasksRequest,
            "create_task": CreateTaskRequest,
            "update_task": UpdateTaskRequest,
            "complete_task": CompleteTaskRequest,
            "bulk_update_tasks": BulkUpdateTasksRequest,
            "delete_task": DeleteTaskRequest,
            "list_calendar_events": ListCalendarEventsRequest,
            "create_calendar_event": CreateCalendarEventRequest,
            "update_calendar_event": UpdateCalendarEventRequest,
            "delete_calendar_event": DeleteCalendarEventRequest,
            "add_task_to_calendar": AddTaskToCalendarRequest,
            "remove_task_from_calendar": RemoveTaskFromCalendarRequest,
            "get_today_overview": GetTodayOverviewRequest,
            "plan_my_day": PlanMyDayRequest,
            "estimate_task_effort": EstimateTaskEffortRequest,
            "apply_day_plan": ApplyDayPlanRequest,
            "save_project_context": SaveProjectContextRequest,
        }

        request_model = request_models.get(tool_name)

        if request_model is None:
            return {"data": {"error": f"No request model for tool: {tool_name}"}}

        request = request_model(**args)

        return tool_func(db, request)

    except Exception as exc:
        return {"data": {"error": str(exc)}}

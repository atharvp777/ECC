import logging
import groq
from groq import Groq
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.database import get_db
from app.services.tool_dispatcher import execute_tool
from app.services.google_calendar import get_upcoming_events, is_connected

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Calendar write routing constants
# ----------------------------------------------------------------------
# The system timezone is UTC+05:30. The planner is told about the current
# local time, but every date is resolved server-side, never by the model.
SYSTEM_TIMEZONE = "Asia/Kolkata"

CALENDAR_WRITE_TOOLS = {
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
}

TASK_TOOLS = {"create_task", "update_task", "complete_task"}

_CALENDAR_NOT_CREATED_MESSAGE = (
    "I couldn't add that event to Google Calendar. No calendar event was created."
)

_WRITE_ACCESS_ERROR_HINTS = (
    "write access",
    "reconnect",
    "re-authorize",
    "not connected",
    "not granted",
    "permission",
    "insufficient",
)


def _is_calendar_read_request(text: str) -> bool:
    """True when the user is only asking to see calendar events."""
    lower = text.lower()
    markers = (
        "what", "list", "show", "view", "upcoming", "display",
        "do i have", "any events", "next event", "what's on", "whats on",
        "my calendar events", "check my calendar", "see my calendar",
    )
    return any(m in lower for m in markers)


def _is_calendar_write_request(text: str) -> bool:
    """True when the user clearly asks to add/schedule a calendar event.

    Read intents ("what's on my calendar?") never count as writes. A generic
    "remind me to..." without a date is left to the planner.
    """
    lower = text.lower().strip()
    if not lower:
        return False
    if _is_calendar_read_request(lower):
        return False

    # 1. Explicit calendar reference with a scheduling verb.
    if "calendar" in lower and any(
        v in lower for v in ("add", "create", "put", "schedule", "book", "remind", "set", "make")
    ):
        return True

    # 2. A scheduled reminder: reminder wording + a date/time anchor.
    if ("remind" in lower or "reminder" in lower) and any(
        d in lower
        for d in ("tomorrow", "today", "next", " at ", "on monday", "on tuesday",
                  "on wednesday", "on thursday", "on friday", "on saturday", "on sunday")
    ):
        return True

    # 3. Scheduling/appointment wording.
    if any(
        v in lower
        for v in ("schedule", "appointment", "book a meeting", "schedule a meeting",
                  "schedule an event", "book an appointment", "set an appointment",
                  "set a meeting", "put a meeting")
    ):
        return True

    return False


def _calendar_write_failure_message(error_text: str) -> str:
    """Turn a failed calendar write into an honest, user-readable message."""
    lower = error_text.lower()
    if any(hint in lower for hint in _WRITE_ACCESS_ERROR_HINTS):
        return error_text
    return _CALENDAR_NOT_CREATED_MESSAGE


def _render_created_event(data) -> str:
    """Render a created calendar event only from a successful API response."""
    summary = data.get("summary") or "(no title)"
    start = data.get("start") or {}
    start_dt = start.get("dateTime") or start.get("date") or ""
    return f'Created calendar event "{summary}" starting at {start_dt}.'


def _safe_sync_reason(error_text: str) -> str:
    """Turn a stored calendar_sync_error into a safe, user-readable reason."""
    if not error_text:
        return "unknown Google Calendar error"
    lower = error_text.lower()
    if any(hint in lower for hint in _WRITE_ACCESS_ERROR_HINTS):
        return error_text
    return "Google Calendar is unavailable right now"


def _render_task_created(data) -> str:
    """Render a created task, honestly including calendar sync results.

    Task succeeds + Calendar succeeds → both reported.
    Task succeeds + Calendar fails   → task reported, safe sync reason given.
    """
    if data.google_calendar_event_id and not data.calendar_sync_error:
        return f'Created task "{data.title}" and added it to your Google Calendar.'
    if data.calendar_sync_error:
        reason = _safe_sync_reason(data.calendar_sync_error)
        return f'Created task "{data.title}", but I couldn\'t add it to your Google Calendar: {reason}'
    tail = f' in project ID {data.project_id}.' if data.project_id else "."
    return f'Created task "{data.title}"{tail}'


def _render_task_updated(data) -> str:
    base = f"Updated task {data.id}."
    if data.calendar_sync_error:
        return f"{base} Calendar sync failed: {_safe_sync_reason(data.calendar_sync_error)}"
    return base


def _render_task_calendar_linked(data) -> str:
    if data.google_calendar_event_id and not data.calendar_sync_error:
        return f'Added "{data.title}" to your Google Calendar.'
    reason = _safe_sync_reason(data.calendar_sync_error)
    return f'I couldn\'t add "{data.title}" to your Google Calendar: {reason}'


def _render_task_calendar_removed(data) -> str:
    if not data.google_calendar_event_id and not data.calendar_sync_error:
        return f'Removed "{data.title}" from your Google Calendar.'
    reason = _safe_sync_reason(data.calendar_sync_error)
    return f'I couldn\'t remove "{data.title}" from your Google Calendar: {reason}'


class AIServiceError(Exception):
    """Raised when an AI request fails and only a safe message may reach the user."""

# ----------------------------------------------------------------------
# System prompt & context helpers (unchanged from previous version)
# ----------------------------------------------------------------------
SYSTEM_PROMPT = """You are the Engineering Command Center AI — a sharp, concise assistant built for Atharv, a mechanical engineering student and Formula SAE (electric vehicle) team member.

You have real-time access to Atharv's projects, tasks, notes, and meetings. Use this context to give specific, actionable answers — not generic ones.

Your personality:
- Direct and efficient. No filler. No "Great question!".
- Think like a senior engineer: practical, prioritization-aware, aware of deadlines.
- When you see overdue tasks or critical items, flag them proactively.
- Use bullet points for lists, plain prose for explanations.
- You know about: eBAJA, AgroVault, Formula SAE EV rules, mechanical engineering, Python, software development.

When asked about tasks/projects, reference the actual data provided. Never make up task names or project details."""


def _friendly_ai_error_message(exc: Exception) -> str:
    """Return a safe, human-readable message for an AI request failure.

    The real exception is logged by the caller; the frontend only ever sees
    one of these strings — never a traceback or internal detail.
    """
    if not settings.GROQ_API_KEY:
        return (
            "The AI service isn't configured yet. "
            "Add GROQ_API_KEY to backend/.env and restart the backend."
        )

    auth_error = getattr(groq, "AuthenticationError", None)
    rate_error = getattr(groq, "RateLimitError", None)
    conn_error = getattr(groq, "APIConnectionError", None)
    status_error = getattr(groq, "APIStatusError", None)

    if auth_error and isinstance(exc, auth_error):
        return "The AI API key is invalid or was rejected. Check GROQ_API_KEY in backend/.env."
    if rate_error and isinstance(exc, rate_error):
        return "The AI service is rate-limited right now. Please wait a moment and try again."
    if conn_error and isinstance(exc, conn_error):
        return "Couldn't reach the AI service. Check your internet connection and try again."
    if status_error and isinstance(exc, status_error):
        return "The AI service returned an error. Please try again in a moment."
    return "I couldn't process that request because of an unexpected AI service error. Please try again."

def _build_context(db: Session) -> str:
    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)
    
    lines = [f"\n--- LIVE CONTEXT (as of {now.strftime('%Y-%m-%d %H:%M UTC')}) ---\n"]

    from app.models.project import Project
    from app.models.task import Task
    from app.models.note import Note
    from app.models.meeting import Meeting

    projects = db.query(Project).filter(Project.status == "ACTIVE").all()
    if projects:
        lines.append("## Active Projects")
        for p in projects:
            task_count = len(p.tasks)
            done = sum(1 for t in p.tasks if t.status == "DONE")
            lines.append(
                f"- ID: {p.id} | Name: **{p.name}** | Category: {p.category} "
                f"| Progress: {done}/{task_count} tasks done"
            )
        lines.append("")

    overdue = (
        db.query(Task)
        .filter(Task.deadline < now_naive, Task.status != "DONE")
        .order_by(Task.deadline.asc())
        .limit(10)
        .all()
    )
    if overdue:
        lines.append("## Overdue Tasks")
        for t in overdue:
            deadline = t.deadline.replace(tzinfo=timezone.utc)
            days = (now - deadline).days
            proj = t.project.name if t.project else "No project"
            lines.append(f"- [{t.priority.upper()}] {t.title} — {days}d overdue ({proj})")
        lines.append("")

    week_end = now_naive + timedelta(days=7)
    upcoming = (
        db.query(Task)
        .filter(Task.deadline >= now_naive, Task.deadline <= week_end, Task.status != "DONE")
        .order_by(Task.deadline.asc())
        .limit(15)
        .all()
    )
    if upcoming:
        lines.append("## Upcoming This Week")
        for t in upcoming:
            dl = t.deadline.strftime("%b %d")
            proj = t.project.name if t.project else "Personal"
            lines.append(f"- [{t.priority.upper()}] {t.title} — due {dl} ({proj})")
        lines.append("")

    critical = (
        db.query(Task)
        .filter(Task.priority == "CRITICAL", Task.status != "DONE")
        .limit(5)
        .all()
    )
    if critical:
        lines.append("## Critical Open Tasks")
        for t in critical:
            lines.append(f"- {t.title}" + (f" — due {t.deadline.strftime('%b %d')}" if t.deadline else ""))
        lines.append("")

    notes = db.query(Note).order_by(Note.updated_at.desc()).limit(5).all()
    if notes:
        lines.append("## Recent Notes")
        for n in notes:
            lines.append(f"- {n.title}")
        lines.append("")

    recent_meetings = db.query(Meeting).order_by(Meeting.held_at.desc()).limit(3).all()
    if recent_meetings:
        lines.append("## Recent Meetings")
        for m in recent_meetings:
            pending = sum(1 for a in m.action_items if not a.is_done)
            lines.append(f"- {m.title} ({m.held_at.strftime('%b %d')}) — {pending} open action items")
        lines.append("")

    lines.append("--- END CONTEXT ---\n")

    # ---- Calendar events (if connected) ----
    try:
        if is_connected():
            events = get_upcoming_events(days=7, max_results=10)
            if events:
                lines.insert(-1, "## Upcoming Calendar Events (7 days)")
                for e in events:
                    lines.insert(-1, f"- {e['title']} — {e['start'][:10]}")
                lines.insert(-1, "")
    except Exception:
        pass

    return "\n".join(lines)


def _maybe_rag(user_message: str) -> Optional[str]:
    triggers = [
        "/doc", "rulebook", "datasheet", "according to the", "in the document",
        "specification", "what does the", "fmea", "regulation", "requirement",
        "clause", "section", "page", "standard"
    ]
    lower = user_message.lower()
    if any(t in lower for t in triggers):
        from app.services.knowledge_service import answer_from_docs
        result = answer_from_docs(user_message.replace("/doc", "").strip())
        if result["sources"]:
            return f"{result['answer']}\n\n*Sources: {', '.join(result['sources'])}*"
    return None


# ----------------------------------------------------------------------
# Tool‑call detection & execution
# ----------------------------------------------------------------------
import re, json

def extract_tool_call(message: str) -> Optional[dict]:
    """
    Detect a tool request of the form:
        /tool <tool_name> <json_args>
    The JSON part must be a valid object.
    """
    m = re.search(r'^/tool\s+(\w+)\s+(.+)$', message, re.DOTALL | re.MULTILINE)
    if not m:
        return None
    tool_name = m.group(1)
    args_str = m.group(2)
    try:
        args = json.loads(args_str)
        return {"tool": tool_name, "args": args}
    except json.JSONDecodeError:
        return None
    return None

def plan_tool_call(user_message: str, context: str) -> Optional[dict]:
    """
    Convert a natural-language action request into a tool call.

    Returns:
        {"tool": "...", "args": {...}}
        or None when no tool action is required.
    """
    system_timezone = SYSTEM_TIMEZONE
    now_local = datetime.now(ZoneInfo(system_timezone))

    planner_prompt = f"""
You are the tool-planning layer for an Engineering Command Center.

Your job is to convert the user's request into ONE tool call when an
action or database operation is clearly requested.

AVAILABLE TOOLS:

1. list_projects
Arguments: {{}}

2. create_project
Arguments:
{{"name": "string", "category": "baja | agrovault | college | personal | internship or null"}}

3. update_project
Arguments:
{{"project_id": integer, "name": "string", "category": "baja | agrovault | college | personal | internship or null"}}

4. list_tasks
Arguments: {{}}

5. create_task
Use for a task or todo, including a task the user wants to work on at a
scheduled time. Arguments:
{{"title": "string",
  "priority": "LOW | MEDIUM | HIGH | CRITICAL",
  "deadline_when": "the user's DUE-DATE phrase passed VERBATIM, e.g. 'Friday',
                    'tomorrow', '2026-08-20'. null when there is no due date.",
  "project_name": "string or null",
  "when": "the user's WORK-TIME date phrase passed VERBATIM, e.g. 'tomorrow',
           'Friday', '2026-08-20'. null unless the user scheduled work time.",
  "start_time": "explicit 24-hour local time 'HH:MM' if the user gave a time
                 (e.g. '15:00' for 3pm), else null",
  "duration_minutes": "integer, default 60",
  "schedule_on_calendar": "true ONLY when the user wants this task blocked as
                            calendar work time (work on X at TIME / from A to B)."}}
Do NOT compute dates/times yourself.

6. update_task
Arguments:
{{"task_id": integer, "title": "string or null",
  "priority": "string or null", "deadline_when": "string or null",
  "status": "string or null", "when": "string or null",
  "start_time": "string or null", "duration_minutes": 60,
  "schedule_on_calendar": "true or false"}}

7. complete_task
Arguments:
{{"task_id": integer}}

8. list_calendar_events
Arguments: {{}}

9. create_calendar_event
Use ONLY when the user asks to add, schedule, book or get a reminder about a
real calendar event / appointment on a date.
Arguments:
{{"summary": "string",
  "description": "string or null",
  "when": "the user's date phrase passed through VERBATIM, e.g. 'tomorrow',
          'next Monday', '2026-08-20', 'today'. null only if the user gave
          no date/time at all.",
  "start_time": "explicit 24-hour local time 'HH:MM' if the user gave a time
                 (e.g. '15:00' for 3pm), else null",
  "duration_minutes": "integer, default 60",
  "timezone": "Asia/Kolkata"}}
Do NOT compute start/end yourself. The current date is supplied below and the
'when' phrase is resolved by the server.

10. update_calendar_event
Arguments:
{{"event_id": "string (must come from the user's request or a recent listing — never invent one)",
  "summary": "string", "description": "string or null",
  "when": "string or null", "start_time": "string or null",
  "duration_minutes": 60, "timezone": "Asia/Kolkata"}}

11. delete_calendar_event
Arguments:
{{"event_id": "string (must come from the user's request — never invent one)"}}

12. add_task_to_calendar
Use when the user asks to put an EXISTING task on the calendar.
Arguments:
{{"task_id": integer, "when": "date phrase verbatim or null",
  "start_time": "HH:MM or null", "duration_minutes": 60,
  "timezone": "Asia/Kolkata"}}

13. remove_task_from_calendar
Use when the user asks to remove an EXISTING task from the calendar.
Arguments:
{{"task_id": integer}}

RULES:

- Return NONE if the user is only asking a general question.
- Return a tool call if the user clearly wants an action.
- Never invent a project_id.
- When the user mentions a project by name, pass its exact project_name.
- For create_project:
  - Use one of the valid project categories when category is specified.
  - If no category is specified, use personal.
- For create_task:
  - Extract the task title from the request.
  - If the user specifies a project, use that project's exact project_name.
  - If no project is specified, use null.
  - If no deadline is specified, use null.
  - If no priority is specified, use MEDIUM.
- Do not assign a task to a project merely because it is the first
  project in the context.
- CALENDAR ROUTING (IMPORTANT):
  - DEADLINE vs SCHEDULE:
    - "finish X by Friday", "submit by ...", "due Friday", "create a task to
      finish X tomorrow" describe when a task is DUE → create_task with
      deadline_when and schedule_on_calendar=false (no calendar event).
    - "work on X Friday from 3 PM to 4 PM", "schedule time tomorrow to X",
      "work on X tomorrow at 4 PM" describe time BLOCKED for work → create_task
      with when/start_time/duration_minutes and schedule_on_calendar=true
      (one operation that creates the task AND its calendar event).
  - "reminder", "appointment", "event", "meeting", "book" that are NOT a task
    describe a real scheduled calendar event → use create_calendar_event (or
    list_calendar_events for "what are my calendar events?").
  - "put my <task> on my calendar" / "add my <task> to my calendar" →
    add_task_to_calendar. "remove my <task> from my calendar" →
    remove_task_from_calendar.
  - Do NOT convert a calendar request into create_task, UNLESS it is genuinely
    a task being scheduled for work (then schedule_on_calendar=true).
  - A task is appropriate only when the user asks to create/manage a task or todo.
  - "remind me tomorrow to ..." should create a calendar event when the user is
    clearly asking for a scheduled reminder.
  - "what are my calendar events?" remains list_calendar_events.
- Never invent a calendar event_id. Only pass one the user mentioned.
- Return ONLY valid JSON.
- Do not use markdown.
- Do not explain your decision.

CURRENT DATE CONTEXT:
The current date/time on the server is {now_local:%Y-%m-%d %H:%M %A}
in timezone {system_timezone} (UTC+05:30).
Use it only to understand relative dates like "today" or "tomorrow". Always
pass the user's own date phrase in "when" verbatim — never compute the event
start/end times yourself.

LIVE CONTEXT:
{context}

USER REQUEST:
{user_message}

Return exactly one of:

NONE

or:

{{"tool":"create_task","args":{{"title":"Check battery wiring",
"priority":"MEDIUM","deadline":null,"project_name":"BAJA HV"}}}}

or for a calendar event:

{{"tool":"create_calendar_event","args":{{"summary":"Get white shirt from ayu",
"description":null,"when":"tomorrow","start_time":null,
"duration_minutes":60,"timezone":"Asia/Kolkata"}}}}
"""

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)

        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": planner_prompt,
                }
            ],
            max_tokens=300,
            temperature=0,
        )

        raw = response.choices[0].message.content

        if raw == "NONE":
            return None

        # Handle accidental markdown fences from the model.
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed = json.loads(raw)

        if not isinstance(parsed, dict):
            return None

        if "tool" not in parsed or "args" not in parsed:
            return None

        return parsed

    except Exception as exc:
        logger.warning("Tool planner failed for request; falling back to general chat: %s", exc)
        return None

def chat_with_ai(messages: List[dict], db: Session) -> str:
    """
    Main entry point used by the chat router.
    1️⃣ Build the normal context (projects, tasks, notes, calendar).
    2️⃣ Look for a ``/tool`` directive in the latest user message.
    3️⃣ If present, dispatch to ``execute_tool`` and turn the result into
       a natural‑language reply.
    4️⃣ Otherwise fall back to the original LLM call.
    """
    # ---- 1️⃣ Build context -------------------------------------------------
    context = _build_context(db)

    # ---- 2️⃣ Detect tool request -------------------------------------------
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    calendar_write_requested = _is_calendar_write_request(last_user)
    tool_call = extract_tool_call(last_user)
    planned_tool_call = False

    if tool_call is None:
        tool_call = plan_tool_call(last_user, context)
        planned_tool_call = tool_call is not None

    if tool_call:
        tool_name = tool_call["tool"]
        args = tool_call["args"]

        if planned_tool_call and tool_name == "create_task":
            if args.get("project_name") is None and args.get("project_id") is not None:
                return "Tool 'create_task' failed: planner must use project_name, not project_id."

        # A calendar write must never be silently converted into a task. If the
        # planner mis-routes a clear calendar request to a task tool, refuse
        # without creating anything and report honestly — unless the planner
        # correctly chose create_task WITH schedule_on_calendar, which is the
        # legitimate "create task + calendar event" orchestration path.
        if (
            calendar_write_requested
            and tool_name in TASK_TOOLS
            and not (tool_name == "create_task" and args.get("schedule_on_calendar"))
        ):
            return (
                "I couldn't add that to your Google Calendar — no calendar event "
                "was created. To schedule a calendar event, use a clear time, e.g. "
                "'schedule a meeting tomorrow at 3pm'."
            )

        # ---- 3️⃣ Execute the tool -------------------------------------------
        try:
            result = execute_tool(tool_name, args, db)
            # Handle tool execution errors before trying to render the result.
            data = result.get("data")

            if isinstance(data, dict) and "error" in data:
                if calendar_write_requested and tool_name in CALENDAR_WRITE_TOOLS:
                    return _calendar_write_failure_message(data["error"])
                return f"Tool '{tool_name}' failed: {data['error']}"

            if data is None:
                if calendar_write_requested and tool_name in CALENDAR_WRITE_TOOLS:
                    return _CALENDAR_NOT_CREATED_MESSAGE
                return f"Tool '{tool_name}' failed: no result was returned."

            # ---- 4️⃣ Render a concise, user‑friendly reply --------------------
            reply_map = {
                "list_projects": lambda: (
                "Projects: " + ", ".join(p.name for p in data)
                ),

            "create_project": lambda: (
                f'Created project "{data.name}".'
            ),

            "update_project": lambda: (
                f'Updated project "{data.name}".'
            ),

            "list_tasks": lambda: (
                "Tasks: " + "; ".join(
                    f"[{t.priority.upper()}] {t.title}"
                    for t in data
                )
                if data
                else "No tasks found."
            ),

            "create_task": lambda: _render_task_created(data),

            "update_task": lambda: _render_task_updated(data),

            "complete_task": lambda: (
                f"Marked task {data.id} as completed."
            ),

            "list_calendar_events": lambda: (
                "Calendar events: " + "; ".join(
                    f"{e['title']} ({e['start'][:10]})"
                    for e in data
                )
                if data
                else "No upcoming events."
            ),

            "create_calendar_event": lambda: _render_created_event(data),

            "update_calendar_event": lambda: (
                f"Updated calendar event {data['id']}."
            ),

            "delete_calendar_event": lambda: (
                f"Deleted calendar event {data['event_id']}."
            ),

            "add_task_to_calendar": lambda: _render_task_calendar_linked(data),

            "remove_task_from_calendar": lambda: _render_task_calendar_removed(data),
        }

            # Only claim a calendar event was created after the API returned a
            # real event ID. Never fabricate success.
            if calendar_write_requested and tool_name == "create_calendar_event":
                if not data.get("id"):
                    logger.warning(
                        "create_calendar_event returned no event ID; not reporting success"
                    )
                    return _CALENDAR_NOT_CREATED_MESSAGE

            render = reply_map.get(tool_name)
            if render:
                return render()

            # Fallback for any tool without a dedicated renderer. This is not
            # a fake success: error results were already handled above.
            logger.warning("No reply renderer registered for tool '%s'", tool_name)
            return f"Done — {tool_name.replace('_', ' ')} succeeded."
        except Exception as exc:
            logger.exception("Tool execution failed for '%s'", tool_name)
            if calendar_write_requested and tool_name in CALENDAR_WRITE_TOOLS:
                return _calendar_write_failure_message(str(exc))
            return (
                "Sorry, I couldn't complete that action. The tool ran into an "
                "unexpected error. Please try again."
            )

    # ---- 4️⃣ Calendar write requested but no write tool ran -----------------
    # Never let the free-form LLM claim a calendar event was created.
    if calendar_write_requested:
        from app.services.google_calendar import has_write_scope

        if not is_connected():
            return (
                "Google Calendar isn't connected. Connect it before creating "
                "calendar events."
            )
        if not has_write_scope():
            from app.services.google_calendar import WRITE_SCOPE_ERROR_MESSAGE
            return WRITE_SCOPE_ERROR_MESSAGE
        return _CALENDAR_NOT_CREATED_MESSAGE

    # ---- 5️⃣ No tool request – fall back to LLM ----------------------------
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not configured – AI chat unavailable")
        return (
            "The AI service isn't configured yet. "
            "Add GROQ_API_KEY to backend/.env and restart the backend."
        )

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        full_messages = [
            {"role": "system", "content": SYSTEM_PROMPT + context},
            *messages,
        ]
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=full_messages,
            max_tokens=1024,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if not content or not isinstance(content, str):
            raise ValueError("AI returned an empty or malformed response")
        return content
    except Exception as exc:
        logger.exception("AI chat completion failed")
        raise AIServiceError(_friendly_ai_error_message(exc)) from exc

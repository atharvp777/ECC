import logging
import groq
from groq import Groq
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.database import get_db
from app.services.ai_providers import (
    AIProviderError,
    complete_text,
    configured_message as ai_provider_configured_message,
    is_configured as ai_provider_configured,
)
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

TASK_TOOLS = {"create_task", "update_task", "complete_task", "bulk_update_tasks", "delete_task"}

# Verbs that mark a task-calendar request as a MOVE/RESCHEDULE (used only to
# pick the response wording: "Moved …" vs "Added …"). The underlying operation
# is unchanged.
_RESCHEDULE_VERBS = ("move", "reschedule", "change", "shift", "postpone")

_CALENDAR_NOT_CREATED_MESSAGE = (
    "I couldn't add that event to Google Calendar. No calendar event was created."
)

_CALENDAR_NOT_UPDATED_MESSAGE = (
    "I couldn't update that calendar event. No changes were made."
)

_CALENDAR_NOT_REMOVED_MESSAGE = (
    "I couldn't remove that task from Google Calendar. The task itself was not deleted."
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


def _calendar_operation_failure_message(tool_name: str) -> str:
    """Op-specific honest failure message for a calendar write."""
    if tool_name == "update_calendar_event":
        return _CALENDAR_NOT_UPDATED_MESSAGE
    if tool_name == "delete_calendar_event":
        return _CALENDAR_NOT_REMOVED_MESSAGE
    return _CALENDAR_NOT_CREATED_MESSAGE


def _calendar_write_failure_message(error_text: str, tool_name: str = "") -> str:
    """Turn a failed calendar write into an honest, user-readable message."""
    lower = error_text.lower()
    if any(hint in lower for hint in _WRITE_ACCESS_ERROR_HINTS):
        return error_text
    return _calendar_operation_failure_message(tool_name)


def _task_calendar_operation(text: str) -> Optional[str]:
    """Classify a calendar write message as a task-calendar operation.

    Returns "add", "reschedule" or "remove" when the message is about a task's
    calendar event, or None when it is a plain calendar event request. The
    planner must never fabricate a calendar event_id for a task — these
    operations are routed through the task-calendar tools server-side.
    """
    lower = text.lower()
    if "task" not in lower:
        return None

    if any(v in lower for v in ("remove", "take off", "unlink")):
        return "remove"
    if any(v in lower for v in ("delete", "cancel")) and (
        "calendar" in lower or "from" in lower
    ):
        return "remove"
    if any(v in lower for v in ("move", "reschedule", "change", "shift", "postpone")):
        return "reschedule"
    if "calendar" in lower and any(v in lower for v in ("add", "put", "link", "schedule")):
        return "add"
    return None


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


def _render_bulk_update_tasks(data) -> str:
    """Render the bulk update result. Only called after a successful commit —
    errors (including an empty target set) are returned before any mutation."""
    count = int(data.get("updated_count", 0) or 0)
    if count == 0:
        return "No tasks were updated."
    applied = data.get("applied") or {}
    bits = []
    if applied.get("status"):
        bits.append(f"marked {applied['status'].lower()}")
    if applied.get("priority"):
        bits.append(f"priority set to {applied['priority'].lower()}")
    if applied.get("deadline"):
        bits.append("deadline updated")
    label = "task" if count == 1 else "tasks"
    detail = f" ({' and '.join(bits)})" if bits else ""
    return f"Updated {count} {label}{detail}."


def _render_task_deleted(data) -> str:
    """Render a successful task deletion. Only reached when the backend tool
    actually deleted the row — a missing task never reaches this renderer."""
    return f"Deleted task {data['deleted_task_id']}."


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


def _is_reschedule_request(text: str) -> bool:
    """True when the user asked to MOVE/RESCHEDULE a task's calendar event.

    Response-rendering only: when True, a successful add_task_to_calendar
    outcome is worded as "Moved …", otherwise "Added …".
    """
    lower = text.lower()
    return any(v in lower for v in _RESCHEDULE_VERBS)


def _render_task_calendar_linked(data, moved: bool = False) -> str:
    if data.google_calendar_event_id and not data.calendar_sync_error:
        if moved:
            return f'Moved "{data.title}" to your Google Calendar.'
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

You have real-time access to Atharv's projects, tasks, notes, and documents. Use this context to give specific, actionable answers — not generic ones.

Your personality:
- Direct and efficient. No filler. No "Great question!".
- Think like a senior engineer: practical, prioritization-aware, aware of deadlines.
- When you see overdue tasks or critical items, flag them proactively.
- Use bullet points for lists, plain prose for explanations.
- You know about: eBAJA, Formula SAE EV rules, mechanical engineering, Python, software development.

When asked about tasks/projects, reference the actual data provided. Never make up task names or project details.

Actions: the backend tool layer can create, update and complete tasks, create/update projects, and manage Google Calendar events. When the user asks for one of these actions the tool layer executes it and hands you the real result — never refuse an action request on the grounds that you cannot mutate data. But never claim an action was performed unless a tool result in the context confirms it; if no tool actually ran, say you could not execute it."""


def _friendly_ai_error_message(exc: Exception) -> str:
    """Return a safe, human-readable message for an AI request failure.

    The real exception is logged by the caller; the frontend only ever sees
    one of these strings — never a traceback or internal detail.
    """
    if isinstance(exc, AIProviderError):
        return str(exc)
    if not ai_provider_configured():
        return ai_provider_configured_message()

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

    projects = db.query(Project).filter(Project.status == "ACTIVE").all()
    if projects:
        lines.append("## Active Projects")
        for p in projects:
            task_count = len(p.tasks)
            done = sum(1 for t in p.tasks if t.status == "DONE")
            desc = f" | Description: {p.description}" if p.description else ""
            doc_part = ""
            if p.documents:
                doc_names = ", ".join(
                    d.title or d.original_filename for d in p.documents
                )
                doc_part = f" | Documents: {doc_names}"
            lines.append(
                f"- ID: {p.id} | Name: **{p.name}** | Category: {p.category} "
                f"| Progress: {done}/{task_count} tasks done{desc}{doc_part}"
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
            lines.append(f"- [ID: {t.id}] [{t.priority.upper()}] {t.title} — {days}d overdue ({proj})")
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
            lines.append(f"- [ID: {t.id}] [{t.priority.upper()}] {t.title} — due {dl} ({proj})")
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
            lines.append(f"- [ID: {t.id}] {t.title}" + (f" — due {t.deadline.strftime('%b %d')}" if t.deadline else ""))
        lines.append("")

    notes = db.query(Note).order_by(Note.updated_at.desc()).limit(5).all()
    if notes:
        lines.append("## Recent Notes")
        for n in notes:
            lines.append(f"- {n.title}")
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
    """Legacy global-knowledge RAG hook. No longer used — document-aware chat
    context is built by ``_project_document_context`` which scopes to the
    project the user is asking about and extracts text on demand.
    """
    return None


# ----------------------------------------------------------------------
# Project document context for AI Chat (on-demand, project-scoped)
# ----------------------------------------------------------------------
_MAX_DOC_TEXT_PER_DOC = 5000
_MAX_DOC_TEXT_TOTAL = 12000

# Wording that asks about a document's CONTENT (as opposed to merely listing
# which documents exist — those are answered from the metadata in
# ``_build_context``).
_DOCUMENT_CONTENT_HINTS = (
    "syllabus", "document", "pdf", "summar", "subject", "exam", "contain",
    "content", "read", "chapter", "topic", "marking", "scheme", "curriculum",
    "unit", "what does", "explain", "describe", "overview", "cover",
    "about the", "what's in", "whats in",
)

# Wording that only asks to LIST documents — no text extraction needed.
_DOCUMENT_LISTING_HINTS = (
    "what documents", "any documents", "documents in", "list documents",
    "which document", "what files", "any files", "documents attached",
    "document in my", "files in my",
)


def _normalize_for_match(text: str) -> str:
    """Lowercase alphanumerics only, so 'In-SEM', 'in sem' and 'insem'
    all normalize to the same key."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _token_set_for_match(text: str) -> set:
    return set(re.findall(r"[a-z0-9]{2,}", text.lower()))


def _wants_document_content(text: str) -> bool:
    """True when the latest user turn asks about document contents.

    Pure listing questions ("what documents are in my X project?") are
    answered from the metadata already present in ``_build_context`` and never
    trigger text extraction.
    """
    lower = (text or "").lower()
    if any(h in lower for h in _DOCUMENT_LISTING_HINTS):
        return False
    return any(h in lower for h in _DOCUMENT_CONTENT_HINTS)


def _identify_document_project(db: Session, text: str) -> Optional[object]:
    """Best-match a project from free-form user wording.

    Handles "my insem project", "In-SEM", "in sem", a document name such as
    "BE SEM 1 Syllabus", and loose variants like "the semester project". The
    whole conversation is scanned so follow-ups ("what is this document
    about?") still resolve to the project named in an earlier turn.
    """
    from app.models.project import Project

    norm_text = _normalize_for_match(text)
    text_tokens = _token_set_for_match(text)

    best = None
    best_score = 0.0
    for proj in db.query(Project).all():
        name_norm = _normalize_for_match(proj.name)
        score = 0.0
        # Exact normalized name hit: "insem" ⊂ "what's the document in my insem project"
        if name_norm and name_norm in norm_text:
            score += 10.0
        proj_tokens = _token_set_for_match(f"{proj.name} {proj.description or ''}")
        score += len(text_tokens & proj_tokens) * 3.0
        # Short project tokens that are substrings of user words ("sem" ⊆ "semester").
        for tok in text_tokens:
            if len(tok) < 4:
                continue
            if any(len(pt) >= 3 and pt in tok for pt in proj_tokens):
                score += 1.0
        # Overlap with this project's document names.
        doc_names = " ".join(d.title or d.original_filename for d in proj.documents)
        score += len(text_tokens & _token_set_for_match(doc_names)) * 2.0
        if score > best_score:
            best_score = score
            best = proj

    return best if best_score > 0 else None


def _project_document_context(db: Session, messages: List[dict]) -> str:
    """Extract the relevant project document text for the chat fallback prompt.

    Returns an empty string when the user is not asking about document
    contents, when no project can be identified, or when the project has no
    documents. The payload is bounded so full document contents are never sent
    on every request. Missing files and unsupported formats are handled
    gracefully (the document is skipped with a note).
    """
    if not messages:
        return ""

    # The listing-vs-content decision uses only the latest user turn; project
    # identification scans the whole conversation so follow-ups resolve.
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    if not _wants_document_content(last_user):
        return ""

    convo = "\n".join(m.get("content", "") for m in messages if m.get("content"))
    project = _identify_document_project(db, convo)
    if project is None or not project.documents:
        return ""

    from app.services.knowledge_service import extract_text_from_file

    blocks = []
    total = 0
    for doc in project.documents:
        text = extract_text_from_file(doc.file_path, doc.mime_type)
        label = doc.title or doc.original_filename
        if not text.strip() or text.startswith("["):
            blocks.append(f"Document: {label} (text could not be extracted)")
            continue
        clipped = text.strip()[:_MAX_DOC_TEXT_PER_DOC]
        total += len(clipped)
        blocks.append(f"Document: {label}\n{clipped}")
        if total >= _MAX_DOC_TEXT_TOTAL:
            break

    if not blocks:
        return ""

    return (
        f"\n--- PROJECT DOCUMENT CONTENTS ({project.name}) ---\n"
        "Use the text below to answer questions about these documents.\n\n"
        + "\n\n".join(blocks)
        + "\n--- END PROJECT DOCUMENT CONTENTS ---\n"
    )


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
{{"name": "string", "category": "personal | baja | jobprep | college | studyabroad or null"}}

3. update_project
Arguments:
{{"project_id": integer, "name": "string", "category": "personal | baja | jobprep | college | studyabroad or null"}}

4. list_tasks
Arguments: {{}}

5. create_task
Use for a task or todo, including a task the user wants to work on at a
scheduled time, and for MEETINGS (a meeting is a task with task_type="meeting").
Arguments:
{{"title": "string",
  "priority": "LOW | MEDIUM | HIGH | CRITICAL",
  "task_type": "work | reminder | meeting (default 'work'; use 'meeting' for
                meetings, 'reminder' for simple reminders)",
  "deadline_when": "the user's DUE-DATE phrase passed VERBATIM, e.g. 'Friday',
                    'tomorrow', '2026-08-20'. null when there is no due date.",
  "project_name": "string or null",
  "when": "the user's WORK-TIME date phrase passed VERBATIM, e.g. 'tomorrow',
           'Friday', '2026-08-20'. null unless the user scheduled work time.",
  "start_time": "explicit 24-hour local time 'HH:MM' if the user gave a time
                 (e.g. '15:00' for 3pm), else null",
  "duration_minutes": "integer, default 60",
  "schedule_on_calendar": "true ONLY when the user wants this task blocked as
                            calendar work time (work on X at TIME / from A to B),
                            or when a MEETING has a date/time (meeting at TIME)."}}
Do NOT compute dates/times yourself.

6. update_task
Arguments:
{{"task_title": "the task reference copied VERBATIM from the user's message —
  exactly the words the user used (e.g. 'the wiring diagram task', 'task 5').
  NEVER paraphrase, generalize or shorten it. The server resolves it.",
  "task_id": "integer ONLY when the context lists that exact task with its ID
              and you are certain it is the one the user means; otherwise null.",
  "title": "string or null",
  "priority": "string or null", "deadline_when": "string or null",
  "status": "string or null", "task_type": "work | reminder | meeting or null",
  "when": "string or null",
  "start_time": "string or null", "duration_minutes": 60,
  "schedule_on_calendar": "true or false"}}

7. complete_task
Arguments:
{{"task_title": "the task reference copied VERBATIM from the user's message,
  exactly as the user said it. The server resolves it.",
  "task_id": "integer ONLY when the context lists that exact task with its ID
              and you are certain it is the one the user means; otherwise null."}}

8. bulk_update_tasks
Use when the user wants to update MULTIPLE tasks at once (e.g. "mark all my
In-SEM tasks done", "complete all overdue tasks", "mark tasks 12, 15, 19
done"). Choose ONE targeting strategy:
- explicit ids: the user gave ids ("tasks 12, 15, 19") → task_ids = [12, 15, 19].
- a scope: the user said ALL/ANY without specific ids →
  scope = "all_open" (every not-done task) or "overdue" (not-done tasks past
  their deadline) or "critical" (not-done critical tasks). When the user named
  a project, pass project_name to scope the selection to that project only.
Arguments:
{{"task_ids": [integer, ...] or null,
  "scope": "all_open | overdue | critical | null",
  "project_name": "the exact project name the user said, or null",
  "status": "done | in_progress | blocked | todo | null",
  "priority": "critical | high | medium | low | null",
  "deadline_when": "the user's due-date phrase passed VERBATIM, or null"}}
Never invent task_ids. Never target every task in the database without the
user's clear intent. When the user says "all my tasks" WITHOUT naming a
project, use scope="all_open" with project_name=null.

9. delete_task
Use when the user wants to DELETE/REMOVE a task (not just complete it).
Arguments:
{{"task_title": "the task reference copied VERBATIM from the user's message,
  exactly as the user said it. The server resolves it.",
  "task_id": "integer ONLY when the context lists that exact task with its ID
              and you are certain it is the one the user means; otherwise null."}}
NEVER invent a task_id.

10. list_calendar_events
Arguments: {{}}

11. create_calendar_event
Use ONLY when the user asks to add, schedule, book or get a reminder about a
real calendar event / appointment on a date. Meetings are NOT events — a
meeting is a create_task call with task_type="meeting".
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

12. update_calendar_event
Use ONLY for a real calendar event (appointment, reminder) that the
user named. NEVER use for a TASK or a MEETING — a task's calendar event is
managed with add_task_to_calendar, which keeps the task row in sync.
Arguments:
{{"event_id": "string (must be the EXACT event id from the user's request or a
              recent calendar listing — never invent one, a task title is never
              an event id)",
  "summary": "string", "description": "string or null",
  "when": "string or null", "start_time": "string or null",
  "duration_minutes": 60, "timezone": "Asia/Kolkata"}}

13. delete_calendar_event
Use ONLY for a real calendar event (appointment, reminder) that the
user named. NEVER use for a TASK or a MEETING — to remove a task from the
calendar use remove_task_from_calendar.
Arguments:
{{"event_id": "string (must be the EXACT event id from the user's request or a
              recent calendar listing — never invent one, a task title is never
              an event id)"}}

14. add_task_to_calendar
Use when the user asks to put an EXISTING task on the calendar.
Arguments:
{{"task_title": "the task reference copied VERBATIM from the user's message —
  exactly the words the user used (e.g. 'the work on the BAJA wiring task',
  'Wiring Diagram'). NEVER paraphrase, generalize or shorten it. The server
  resolves the user's original wording, so a verbatim copy is required.",
  "task_id": "integer ONLY when the context lists that exact task with its ID
              and you are certain it is the one the user means; otherwise null.",
  "when": "the user's date phrase passed VERBATIM, e.g. 'tomorrow', 'Monday',
           '2026-08-21'. MUST be null when the user gave NO date and NO time —
           the server will then ask when to schedule it.",
  "start_time": "explicit 24-hour local time 'HH:MM' if the user gave a time
                 (e.g. '16:00' for 4pm), else null",
  "duration_minutes": 60, "timezone": "Asia/Kolkata"}}
NEVER guess a task_id for a task you cannot see listed with its ID.
Do NOT change the task_title — copy it verbatim from the user's message.
Do NOT invent a when/date — if the user gave no date or time, pass null.

15. remove_task_from_calendar
Use when the user asks to remove an EXISTING task from the calendar.
Arguments:
{{"task_title": "the task reference copied VERBATIM from the user's message —
  exactly the words the user used (e.g. 'the work on the BAJA wiring task',
  'Wiring Diagram'). NEVER paraphrase, generalize or shorten it.",
  "task_id": "integer ONLY when the context lists that exact task with its ID
              and you are certain it is the one the user means; otherwise null."}}
NEVER guess a task_id for a task you cannot see listed with its ID.
Do NOT change the task_title — copy it verbatim from the user's message.

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
- For bulk_update_tasks:
  - When the user gave explicit task ids ("tasks 12, 15, 19"), pass task_ids.
  - When the user said ALL/ANY WITHOUT specific ids, pass a scope. If the user
    named a project, ALSO pass project_name so only that project's tasks are
    touched. Never mutate tasks outside the user's stated scope.
  - "mark all my tasks done" with no project → scope "all_open",
    project_name null.
- For delete_task:
  - Only target a task whose ID appears in the live context or was given
    explicitly. Never invent a task_id.
- For add_task_to_calendar / remove_task_from_calendar:
  - Copy the task_title VERBATIM from the user's message — never paraphrase,
    generalize or shorten it. If the user said "the work on the BAJA wiring
    task", keep those exact words; do NOT reduce it to "the BAJA wiring task".
  - Never guess a task_id. The server resolves the user's wording.
  - For add_task_to_calendar, pass when/start_time VERBATIM from the user. If
    the user gave no date and no time, pass null — do NOT default to "today"
    or "tomorrow"; the server asks the user what time to schedule.
- For update_task / complete_task / delete_task:
  - Copy the task reference VERBATIM from the user's message as task_title.
    The server resolves it deterministically; NEVER guess a task_id.
  - Pass task_id only when the live context lists that exact task with its ID
    and you are certain it is the one the user means.
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
  - "reminder", "appointment", "event", "book" that are NOT a task and NOT a
    meeting describe a real scheduled calendar event → use create_calendar_event
    (or list_calendar_events for "what are my calendar events?").
  - "MEETING" requests are TASKS: "meeting with Prof X tomorrow at 4 PM",
    "schedule a meeting tomorrow", "book a meeting", "set up a meeting",
    "meeting reminder" → create_task with task_type="meeting". When the user
    gives a date/time, pass when/start_time VERBATIM and set
    schedule_on_calendar=true (creates the task AND its Google event). When no
    date/time is given, create the meeting task with when=null and
    schedule_on_calendar=false — never invent a schedule.
  - "put my <task> on my calendar" / "add my <task> to my calendar" →
    add_task_to_calendar. "remove my <task> from my calendar" →
    remove_task_from_calendar.
  - "move <task> to <time>" / "reschedule <task> to <time>" / "change <task>
    to <time>" → add_task_to_calendar with when/start_time VERBATIM. NEVER
    update_calendar_event for a task, and NEVER fabricate an event_id from the
    task title.
  - "take <task> off the calendar" / "remove <task> from the calendar" →
    remove_task_from_calendar.
  - The raw calendar tools (create_calendar_event, update_calendar_event,
    delete_calendar_event) are ONLY for real calendar events, appointments and
    meetings — never for tasks. A task's calendar event is managed with
    add_task_to_calendar / remove_task_from_calendar.
  - Do NOT convert a calendar request into create_task, UNLESS it is genuinely
    a task being scheduled for work (then schedule_on_calendar=true).
  - A task is appropriate only when the user asks to create/manage a task or todo.
  - "remind me tomorrow to ..." should create a calendar event when the user is
    clearly asking for a scheduled reminder.
  - "what are my calendar events?" remains list_calendar_events.
- Never invent a calendar event_id. Only pass one the user mentioned or that
  appeared in a recent listing. A task title is never an event_id — task
  calendar operations use add_task_to_calendar / remove_task_from_calendar.
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
        # The planner prompt is large; passing it as the user message (instead
        # of an empty user turn under a huge system instruction) stops Gemini
        # from echoing the prompt back or emitting a truncated tool call.
        # json_mode pins Gemini's response_mime_type so we get clean JSON.
        raw = complete_text(
            system=None,
            messages=[{"role": "user", "content": planner_prompt}],
            max_tokens=1024,
            temperature=0,
            json_mode=True,
        )

        if not raw or not raw.strip():
            return None

        raw = raw.strip()

        if raw == "NONE":
            return None

        # Handle accidental markdown fences from the model.
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()

        # Some Gemini outputs arrive in the SDK function-call shape
        # {"name": "...", "arguments": {...}} instead of the planner JSON
        # contract {"tool": "...", "args": {...}}. Normalize it here.
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # The model sometimes emits prose before/after the JSON object.
            # Extract the first balanced JSON object if one exists.
            parsed = _extract_embedded_json(raw)

        # json_mode forces valid JSON, so a "no tool" answer may arrive as the
        # JSON string "NONE" rather than the bare token NONE.
        if parsed == "NONE":
            return None

        if not isinstance(parsed, dict):
            return None

        if "name" in parsed and "arguments" in parsed and "tool" not in parsed:
            parsed = {"tool": parsed["name"], "args": parsed["arguments"]}

        if "tool" not in parsed or "args" not in parsed:
            return None

        if not isinstance(parsed.get("args"), dict):
            return None

        return {"tool": parsed["tool"], "args": parsed["args"]}

    except Exception as exc:
        logger.warning("Tool planner failed for request; falling back to general chat: %s", exc)
        return None


def _extract_embedded_json(raw: str):
    """Extract the first balanced JSON object embedded in free text.

    Gemini sometimes wraps its tool call in prose (or appends reasoning after
    the closing brace). We scan for the first '{' and try each candidate end
    that yields a valid JSON object, so a trailing explanation never breaks
    the planner protocol.
    """
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
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

        # Response-wording flag (rendering only): reschedules say "Moved …",
        # fresh adds say "Added …". The operation itself is unchanged.
        rescheduled = _is_reschedule_request(last_user)

        # ---- Task-calendar write normalization -----------------------------
        # The planner must NEVER fabricate a calendar event_id from a task
        # title (e.g. "QA scheduled task"). When a planned calendar write
        # clearly targets a TASK, re-route it through the task-calendar tools:
        # the server resolves the task and its linked event, and the task row
        # stays in sync with Google Calendar.
        if planned_tool_call and tool_name in CALENDAR_WRITE_TOOLS:
            op = _task_calendar_operation(last_user) if calendar_write_requested else None
            if op == "remove":
                tool_name = "remove_task_from_calendar"
                args = {}
            elif op in ("add", "reschedule"):
                rescheduled = rescheduled or op == "reschedule"
                tool_name = "add_task_to_calendar"
                args = {
                    "when": args.get("when"),
                    "start_time": args.get("start_time"),
                    "duration_minutes": args.get("duration_minutes", 60),
                    "timezone": args.get("timezone", SYSTEM_TIMEZONE),
                }
            else:
                # The planner sometimes routes an EXISTING task to the raw
                # calendar tools. If the event summary (create) or event_id
                # (update/delete, where the planner may fabricate one from the
                # task title) matches a task title, re-route through the
                # task-calendar tools so the server resolves the task and its
                # linked event (idempotent update, never a fabricated
                # duplicate, never a wrong event deleted). This must hold even
                # when the message has no literal "calendar" word ("move X to
                # tomorrow").
                from app.models.task import Task

                raw_reference = args.get("summary") or args.get("event_id")
                if raw_reference:
                    ref = str(raw_reference).strip()
                    matched_task = (
                        db.query(Task)
                        .filter(func.lower(func.trim(Task.title)) == ref.lower())
                        .first()
                    )
                    if matched_task is not None:
                        if tool_name == "delete_calendar_event":
                            tool_name = "remove_task_from_calendar"
                            args = {"task_title": ref}
                        else:
                            # update_calendar_event aimed at a task is a
                            # reschedule → word the reply as "Moved".
                            rescheduled = rescheduled or tool_name == "update_calendar_event"
                            tool_name = "add_task_to_calendar"
                            args = {
                                "task_title": ref,
                                "when": args.get("when"),
                                "start_time": args.get("start_time"),
                                "duration_minutes": args.get("duration_minutes", 60),
                                "timezone": args.get("timezone", SYSTEM_TIMEZONE),
                            }

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
            result = execute_tool(
                tool_name,
                args,
                db,
                user_message=last_user if planned_tool_call else None,
            )
            # Handle tool execution errors before trying to render the result.
            data = result.get("data")

            # Task-reference resolution results (ambiguous/not-found) are already
            # user-facing clarification messages — render them directly.
            if (
                isinstance(data, dict)
                and data.get("reply_direct")
                and tool_name
                in (
                    "add_task_to_calendar",
                    "remove_task_from_calendar",
                    "update_task",
                    "complete_task",
                    "delete_task",
                )
            ):
                return data["error"]

            if isinstance(data, dict) and "error" in data:
                if calendar_write_requested and tool_name in CALENDAR_WRITE_TOOLS:
                    return _calendar_write_failure_message(data["error"], tool_name=tool_name)
                return f"Tool '{tool_name}' failed: {data['error']}"

            if data is None:
                if calendar_write_requested and tool_name in CALENDAR_WRITE_TOOLS:
                    return _calendar_operation_failure_message(tool_name)
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

            "bulk_update_tasks": lambda: _render_bulk_update_tasks(data),

            "delete_task": lambda: _render_task_deleted(data),

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

            "add_task_to_calendar": lambda: _render_task_calendar_linked(data, moved=rescheduled),

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
                return _calendar_write_failure_message(str(exc), tool_name=tool_name)
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
        op = _task_calendar_operation(last_user)
        if op == "remove":
            return _CALENDAR_NOT_REMOVED_MESSAGE
        if op == "reschedule":
            return _CALENDAR_NOT_UPDATED_MESSAGE
        return _CALENDAR_NOT_CREATED_MESSAGE

# ---- 5️⃣ No tool request – fall back to LLM ----------------------------
    if not ai_provider_configured():
        logger.error("AI provider is not configured – AI chat unavailable")
        return ai_provider_configured_message()

    try:
        doc_context = _project_document_context(db, messages)
        content = complete_text(
            system=SYSTEM_PROMPT + context + doc_context,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
        if not content or not isinstance(content, str):
            raise ValueError("AI returned an empty or malformed response")
        return content
    except Exception as exc:
        logger.exception("AI chat completion failed")
        raise AIServiceError(_friendly_ai_error_message(exc)) from exc

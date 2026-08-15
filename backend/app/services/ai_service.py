from groq import Groq
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.core.config import settings
from app.core.database import get_db
from app.services.tool_dispatcher import execute_tool
from app.services.google_calendar import get_upcoming_events, is_connected

# ----------------------------------------------------------------------
# System prompt & context helpers (unchanged from previous version)
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are the Engineering Command Center AI – a sharp, concise assistant built for Atharv, a mechanical engineering student and Formula SAE (electric vehicle) team member.

You have real-time access to Atharv's projects, tasks, notes, and meetings. Use this context to give specific, actionable answers – not generic ones.

Your personality:
- Direct and efficient. No filler. No "Great question!".
- Think like a senior engineer: practical, prioritization-aware, aware of deadlines.
- When you see overdue tasks or critical items, flag them proactively.
- Use bullet points for lists, plain prose for explanations.
- You know about: eBAJA, AgroVault, Formula SAE EV rules, mechanical engineering, Python, software development.

When asked about tasks/projects, reference the actual data provided. Never make up task names or project details."""

def _build_context(db: Session) -> str:
    """
    Build the live context string that is prepended to every AI prompt.
    Handles timezone‑aware vs naive datetime comparisons robustly.
    """
    now = datetime.now(timezone.utc)

    # Helper: ensure a datetime is timezone‑aware in UTC
    def _make_utc_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

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
            lines.append(f"- **{p.name}** (project_id={p.id}) [{p.category}] – {done}/{task_count} tasks done")
        lines.append("")

    # ------------------------------------------------------------------
    # Overdue tasks (deadline < now)
    # ------------------------------------------------------------------
    overdue = (
        db.query(Task)
        .filter(
            Task.deadline < now,
            Task.status != "DONE",
        )
        .order_by(Task.deadline.asc())
        .limit(10)
        .all()
    )
    if overdue:
        lines.append("## Overdue Tasks")
        for t in overdue:
            # Ensure deadline is UTC‑aware before subtraction
            deadline_utc = _make_utc_aware(t.deadline)
            days = (now - deadline_utc).days
            proj = t.project.name if t.project else "No project"
            lines.append(f"- [{t.priority.upper()}] {t.title} – {days}d overdue ({proj})")
        lines.append("")

    # ------------------------------------------------------------------
    # Upcoming tasks (deadline within the next week)
    # ------------------------------------------------------------------
    week_end = now + timedelta(days=7)
    upcoming = (
        db.query(Task)
        .filter(
            Task.deadline >= now,
            Task.deadline <= week_end,
            Task.status != "DONE",
        )
        .order_by(Task.deadline.asc())
        .limit(15)
        .all()
    )
    if upcoming:
        lines.append("## Upcoming This Week")
        for t in upcoming:
            deadline_utc = _make_utc_aware(t.deadline)
            dl = deadline_utc.strftime("%b %d")
            proj = t.project.name if t.project else "Personal"
            lines.append(f"- [{t.priority.upper()}] {t.title} – due {dl} ({proj})")
        lines.append("")

    # ------------------------------------------------------------------
    # Critical open tasks
    # ------------------------------------------------------------------
    critical = (
        db.query(Task)
        .filter(Task.priority == "CRITICAL", Task.status != "DONE")
        .limit(5)
        .all()
    )
    if critical:
        lines.append("## Critical Open Tasks")
        for t in critical:
            lines.append(f"- {t.title}" + (f" – due {t.deadline.strftime('%b %d')}" if t.deadline else ""))
        lines.append("")

    # ------------------------------------------------------------------
    # Recent notes
    # ------------------------------------------------------------------
    notes = db.query(Note).order_by(Note.updated_at.desc()).limit(5).all()
    if notes:
        lines.append("## Recent Notes")
        for n in notes:
            lines.append(f"- {n.title}")
        lines.append("")

    # ------------------------------------------------------------------
    # Recent meetings
    # ------------------------------------------------------------------
    recent_meetings = db.query(Meeting).order_by(Meeting.held_at.desc()).limit(3).all()
    if recent_meetings:
        lines.append("## Recent Meetings")
        for m in recent_meetings:
            pending = sum(1 for a in m.action_items if not a.is_done)
            lines.append(f"- {m.title} ({m.held_at.strftime('%b %d')}) – {pending} open action items")
        lines.append("")

    # ------------------------------------------------------------------
    # Calendar events (if connected)
    # ------------------------------------------------------------------
    try:
        if is_connected():
            events = get_upcoming_events(days=7, max_results=10)
            if events:
                lines.insert(-1, "## Upcoming Calendar Events (7 days)")
                for e in events:
                    lines.insert(-1, f"- {e['title']} – {e['start'][:10]}")
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
# ------------------------------------------------------------------
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
    Ask Groq whether the user's natural-language request requires a tool.
    Returns a tool call dictionary or None.
    """

    planner_prompt = f"""
You are the tool-planning layer of an Engineering Command Center.

Decide whether the user's request requires one of the available tools.

AVAILABLE TOOLS:

1. list_projects
Arguments: {{}}

2. create_project
Arguments:
{{"name": "string", "category": "string"}}

3. update_project
Arguments:
{{"project_id": integer, "name": "string", "category": "string"}}

4. list_tasks
Arguments: {{}}

5. create_task
Arguments:
{{"title": "string", "priority": "LOW | MEDIUM | HIGH | CRITICAL" (default "MEDIUM"), "deadline": "YYYY-MM-DDTHH:MM:SS" (default null), "project_id": integer (default null)}}

6. update_task
Arguments:
{{"task_id": integer}}

7. complete_task
Arguments:
{{"task_id": integer}}

8. list_calendar_events
Arguments: {{}}

IMPORTANT RULES:

- Only return a tool call when the user clearly wants an action or database lookup.
- If the user is asking a general question, return NONE.
- Never invent a project_id.
- Use LIVE CONTEXT to resolve project names to IDs.
  - When a project name is mentioned (e.g., "BAJA HV"), locate that project in the LIVE CONTEXT section. The context lists each active project as "... (project_id=X) ..." where X is the numeric database ID. Use that ID as project_id.
  - If the mentioned project is not found in the LIVE CONTEXT, set project_id to null.
- For create_task, **title is the only required user-provided field**.
  - If **priority** is omitted, treat it as **"MEDIUM"**.
  - If **deadline** is omitted, treat it as **null**.
  - If **project_id** cannot be resolved, treat it as **null**.
  - **Never invent** a project_id or a deadline.
- Return ONLY valid JSON.
- Do not use markdown.
- Do not explain your decision.

LIVE CONTEXT:
{context}

USER REQUEST:
{user_message}

Return exactly one of:

NONE

or:

{{"tool":"create_task","args":{{"title":"wiring diagram","priority":"MEDIUM","deadline":null,"project_id":1}}}}
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

        raw = response.choices[0].message.content.strip()
        # Strip potential markdown code fences that the model may add
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw[3:-3].strip()
        if raw.startswith("```"):
            raw = raw[3:].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()

        if raw == "NONE":
            return None

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        if "tool" not in parsed or "args" not in parsed:
            return None

        return parsed

    except Exception:
        # Restore original behaviour: return None on any error
        return None

def chat_with_ai(messages: List[dict], db: Session) -> str:
    """
    Main entry point used by the chat router.

    1. Build live context.
    2. Detect explicit /tool commands.
    3. Execute tools safely.
    4. Otherwise use Groq for normal conversation.
    """

    # ---- 1. Build live context ---------------------------------------------
    context = _build_context(db)

    # ---- 2. Detect tool request --------------------------------------------
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )

    tool_call = extract_tool_call(last_user)

    if tool_call is None:
        tool_call = plan_tool_call(last_user, context)

    # ---- 3. Execute tool ---------------------------------------------------
    if tool_call:
        tool_name = tool_call["tool"]
        args = tool_call["args"]

        try:
            result = execute_tool(tool_name, args, db)

            # execute_tool returns {"data": ...}
            data = result.get("data")

            # Handle errors returned by the dispatcher.
            if isinstance(data, dict) and "error" in data:
                return f"Tool '{tool_name}' failed: {data['error']}"

            if data is None:
                return f"Tool '{tool_name}' failed: no result was returned."

            # ---- Render tool result ----------------------------------------
            if tool_name == "list_projects":
                if not data:
                    return "No active projects found."

                return "Projects: " + ", ".join(
                    project.name for project in data
                )

            if tool_name == "create_project":
                return f'Created project "{data.name}".'

            if tool_name == "update_project":
                return f'Updated project "{data.name}".'

            if tool_name == "list_tasks":
                if not data:
                    return "No tasks found."

                return "Tasks:\n" + "\n".join(
                    f"- [{task.priority.upper()}] {task.title}"
                    for task in data
                )

            if tool_name == "create_task":
                project_text = (
                    f" in project ID {data.project_id}"
                    if data.project_id
                    else ""
                )

                return f'Created task "{data.title}"{project_text}.'

            if tool_name == "update_task":
                return f"Updated task {data.id}."

            if tool_name == "complete_task":
                return f"Marked task {data.id} as completed."

            if tool_name == "list_calendar_events":
                if not data:
                    return "No upcoming calendar events."

                return "Calendar events:\n" + "\n".join(
                    f"- {event.get('title', 'Untitled')} "
                    f"({event.get('start', '')[:10]})"
                    for event in data
                )

            if tool_name == "create_calendar_event":
                return (
                    f'Created calendar event "{data["summary"]}" '
                    f'starting at {data["start"]}.'
                )

            if tool_name == "update_calendar_event":
                return f"Updated calendar event {data['id']}."

            if tool_name == "delete_calendar_event":
                return (
                    f"Deleted calendar event "
                    f"{data['event_id']}."
                )

            return f"Tool '{tool_name}' executed successfully."

        except Exception as exc:
            return f"Error executing tool: {exc}"

    # ---- 4. Normal LLM conversation ---------------------------------------
    client = Groq(api_key=settings.GROQ_API_KEY)

    full_messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + context,
        },
        *messages,
    ]

    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=full_messages,
        max_tokens=1024,
        temperature=0.7,
    )

    return response.choices[0].message.content

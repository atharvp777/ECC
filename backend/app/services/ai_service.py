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
Arguments:
{{"title": "string",
  "priority": "LOW | MEDIUM | HIGH | CRITICAL",
  "deadline": "YYYY-MM-DDTHH:MM:SS or null",
  "project_name": "string or null"}}

6. update_task
Arguments:
{{"task_id": integer}}

7. complete_task
Arguments:
{{"task_id": integer}}

8. list_calendar_events
Arguments: {{}}

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

{{"tool":"create_task","args":{{"title":"Check battery wiring",
"priority":"MEDIUM","deadline":null,"project_name":"BAJA HV"}}}}
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

    except Exception:
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

        # ---- 3️⃣ Execute the tool -------------------------------------------
        try:
            result = execute_tool(tool_name, args, db)
            # Handle tool execution errors before trying to render the result.
            data = result.get("data")

            if isinstance(data, dict) and "error" in data:
                return f"Tool '{tool_name}' failed: {data['error']}"

            if data is None:
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

            "create_task": lambda: (
                f'Created task "{data.title}"'
                + (
                    f' in project ID {data.project_id}.'
                    if data.project_id
                    else "."
                )
            ),

            "update_task": lambda: (
                f"Updated task {data.id}."
            ),

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

            "create_calendar_event": lambda: (
                f'Created calendar event "{data["summary"]}" '
                f'starting at {data["start"]}.'
            ),

            "update_calendar_event": lambda: (
                f"Updated calendar event {data['id']}."
            ),

            "delete_calendar_event": lambda: (
                f"Deleted calendar event {data['event_id']}."
            ),
        }

            render = reply_map.get(tool_name)
            if render:
                return render()

            # Fallback for any other tool
            return "Tool executed successfully."
        except Exception as exc:
            return f"Error executing tool: {str(exc)}"

    # ---- 4️⃣ No tool request – fall back to LLM ----------------------------
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
    return response.choices[0].message.content

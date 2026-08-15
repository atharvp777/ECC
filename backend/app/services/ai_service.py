from groq import Groq
import json
from typing import Optional
from app.core.config import settings

def plan_tool_call(user_message: str, context: str) -> Optional[dict]:
    """
    Analyze the user message together with the live context and decide which
    tool (if any) should be invoked.  The function returns the parsed tool-call
    dictionary when the planner outputs valid JSON that contains a supported
    ``tool`` key, otherwise it returns ``None``.
    """
    # Build the prompt for the model
    prompt = f"Context: {context}\nUser: {user_message}\nAssistant:"

    client = Groq()
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120,
    )

    # Extract the raw text that the model returned
    raw_content = response.choices[0].message.content

    # Attempt to parse the JSON payload
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return None

    # Validate that the payload describes a known tool
    allowed_tools = {"create_task", "update_task", "complete_task", "list_projects", "list_tasks"}
    if not isinstance(payload, dict) or "tool" not in payload:
        return None
    if payload["tool"] not in allowed_tools:
        return None

    # Optionally, you could perform extra validation on ``payload["args"]`` here.
    return payload

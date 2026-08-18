import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.services.ai_service import chat_with_ai, AIServiceError
from app.core.database import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/chat", tags=["ai"])

logger = logging.getLogger(__name__)

# -------------------------------------------------
# Request / Response models
# -------------------------------------------------
class Message(BaseModel):
    role: str      # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: list[Message]

# -------------------------------------------------
# AI provider status
# -------------------------------------------------
@router.get("/status")
def ai_status():
    """Report the active AI provider and model (no secrets).

    The frontend model badge is built from this response so it always reflects
    the backend's actual configuration instead of a hardcoded label.
    """
    from app.services.ai_providers import (
        active_model,
        active_provider,
        display_name,
        is_configured,
    )
    return {
        "provider": active_provider(),
        "model": active_model(),
        "configured": is_configured(),
        "display": display_name(),
    }


# -------------------------------------------------
# Chat endpoint
# -------------------------------------------------
@router.post("/", response_model=dict)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    messages = [
        {"role": m.role, "content": m.content}
        for m in payload.messages
        if m.role in ("user", "assistant")
    ]

    try:
        reply = chat_with_ai(messages, db)
    except AIServiceError as exc:
        # The service already logged the root cause and produced a safe message.
        reply = str(exc)
    except Exception:
        logger.exception("Unexpected failure in chat endpoint")
        reply = "Something went wrong processing your request. Please try again."

    return {
        "reply": reply,
        "sources": []
    }

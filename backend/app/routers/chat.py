from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.ai_service import chat_with_ai

router = APIRouter(prefix="/chat", tags=["ai"])


class Message(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]  # Full conversation history from frontend


class ChatResponse(BaseModel):
    reply: str


@router.post("/", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    messages = [m.model_dump() for m in payload.messages]
    reply = chat_with_ai(messages, db)
    return ChatResponse(reply=reply)


@router.get("/context-preview")
def preview_context(db: Session = Depends(get_db)):
    """Dev endpoint — see exactly what context the AI receives."""
    from app.services.ai_service import _build_context
    return {"context": _build_context(db)}

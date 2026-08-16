from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.services.ai_service import chat_with_ai
from app.core.database import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/chat", tags=["ai"])

# -------------------------------------------------
# Request / Response models
# -------------------------------------------------
class Message(BaseModel):
    role: str      # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: list[Message]

# -------------------------------------------------
# Chat endpoint
# -------------------------------------------------
@router.post("/", response_model=dict)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    messages = [
        {"role": m.role, "content": m.content}
        for m in payload.messages
    ]

    reply = chat_with_ai(messages, db)

    return {
        "reply": reply,
        "sources": []
    }

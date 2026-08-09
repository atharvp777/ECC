from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.services.knowledge_service import answer_from_docs
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
    """
    Receive the full conversation history, ask Groq (via
    knowledge_service.answer_from_docs) and return the answer.
    """
    # Use the latest user message as the query
    query = payload.messages[-1].content

    # answer_from_docs returns {"answer": "...", "sources": [...]}
    result = answer_from_docs(query)

    # Return exactly what the frontend expects
    return {"answer": result["answer"], "sources": result["sources"]}

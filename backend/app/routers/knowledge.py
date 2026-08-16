from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document
from app.services.knowledge_service import (
    ingest_document, remove_document, search_documents, answer_from_docs
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# ── Background ingestion ──────────────────────────────────────────────────────
def _ingest_bg(doc_id: int, title: str, file_path: str, mime_type: str, db: Session):
    """Run in background after upload so the upload response is instant."""
    try:
        n = ingest_document(doc_id, title, file_path, mime_type)
        # Store extracted chunk count on the document record
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.extracted_text = f"[indexed:{n} chunks]"
            db.commit()
    except Exception as e:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.extracted_text = f"[index error: {str(e)[:200]}]"
            db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/ingest/{doc_id}")
def ingest(doc_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually trigger ingestion for an already-uploaded document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    background.add_task(_ingest_bg, doc.id, doc.title or doc.original_filename, doc.file_path, doc.mime_type, db)
    return {"status": "ingestion started", "doc_id": doc_id}


@router.delete("/index/{doc_id}")
def remove_from_index(doc_id: int):
    """Remove a document's chunks from the search index."""
    remove_document(doc_id)
    return {"status": "removed", "doc_id": doc_id}


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchResult(BaseModel):
    score: float
    doc_id: int
    title: str
    text: str


@router.post("/search", response_model=list[SearchResult])
def search(payload: SearchRequest):
    """Semantic search — returns raw chunks with scores."""
    results = search_documents(payload.query, top_k=payload.top_k)
    return results


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[str]


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    """
    Full RAG: search relevant chunks → ask GPT → return answer + sources.
    Use this for document Q&A from the chat UI.
    """
    result = answer_from_docs(payload.question)
    return result


@router.get("/status")
def index_status():
    """How many chunks are currently indexed."""
    from app.services.knowledge_service import CHUNKS_FILE
    if not CHUNKS_FILE.exists() or CHUNKS_FILE.stat().st_size == 0:
        return {"indexed_chunks": 0, "documents": []}
    import json
    try:
        chunks = json.loads(CHUNKS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"indexed_chunks": 0, "documents": []}
    doc_map: dict[int, str] = {}
    for c in chunks:
        doc_map[c["doc_id"]] = c["title"]
    return {
        "indexed_chunks": len(chunks),
        "documents": [{"doc_id": k, "title": v} for k, v in doc_map.items()],
    }

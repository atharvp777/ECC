import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status, BackgroundTasks
from sqlalchemy.orm import Session
from app.services.knowledge_service import ingest_document, remove_document

from app.core.database import get_db
from app.core.config import settings
from app.models.document import Document
from app.schemas.document import DocumentRead, DocumentUpdate

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
}


@router.get("/", response_model=list[DocumentRead])
def list_documents(
    project_id: int | None = Query(None),
    tag: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Document)
    if project_id is not None:
        query = query.filter(Document.project_id == project_id)
    if tag:
        query = query.filter(Document.tags.contains(tag))
    return query.order_by(Document.created_at.desc()).all()


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    title: str | None = Form(None),
    description: str | None = Form(None),
    tags: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not allowed. Supported: PDF, TXT, MD, DOCX, PNG, JPG.",
        )

    ext = Path(file.filename).suffix
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOADS_DIR / unique_name

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = dest.stat().st_size

    doc = Document(
        filename=unique_name,
        original_filename=file.filename,
        file_path=str(dest),
        mime_type=file.content_type,
        file_size_bytes=file_size,
        title=title or file.filename,
        description=description,
        tags=tags,
        project_id=project_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Auto-ingest into knowledge base (runs in background, won't slow the response)
    doc_id    = doc.id
    doc_title = doc.title or doc.original_filename
    doc_path  = doc.file_path
    doc_mime  = doc.mime_type
    background.add_task(ingest_document, doc_id, doc_title, doc_path, doc_mime)

    return doc


@router.get("/{doc_id}", response_model=DocumentRead)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.patch("/{doc_id}", response_model=DocumentRead)
def update_document(doc_id: int, payload: DocumentUpdate, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # Remove file from disk
    path = Path(doc.file_path)
    if path.exists():
        path.unlink()
    # Remove from knowledge base index
    remove_document(doc.id)
    db.delete(doc)
    db.commit()

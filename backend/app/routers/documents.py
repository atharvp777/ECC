import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.services.knowledge_service import ingest_document, remove_document

from app.core.database import get_db
from app.core.config import settings
from app.models.document import Document
from app.models.project import Project
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

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


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
    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Upload failed: file has no name.")

    safe_filename = Path(file.filename).name
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Upload failed: invalid filename.")

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not allowed. Supported: PDF, TXT, MD, DOCX, PNG, JPG.",
        )

    if project_id is not None:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} does not exist")

    ext = Path(safe_filename).suffix
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOADS_DIR / unique_name

    # Stream to disk in chunks so arbitrarily huge files are never buffered
    # fully in memory; abort as soon as the size limit is exceeded.
    file_size = 0
    with dest.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > MAX_UPLOAD_SIZE_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum upload size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
                )
            f.write(chunk)

    doc = Document(
        filename=unique_name,
        original_filename=safe_filename,
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


@router.get("/{doc_id}/download")
def download_document(doc_id: int, db: Session = Depends(get_db)):
    """Serve the original uploaded file for the given document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    path = Path(doc.file_path).resolve()
    uploads_root = settings.UPLOADS_DIR.resolve()

    # Never serve files outside the application's uploads directory.
    if not path.is_relative_to(uploads_root):
        raise HTTPException(status_code=404, detail="Document file is outside the uploads directory.")

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document file is missing on disk.")

    download_name = Path(doc.original_filename or doc.filename).name
    return FileResponse(
        path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=download_name,
    )


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
    # Remove file from disk. Defense-in-depth: never delete a file outside the
    # application's uploads directory, even if a document row was tampered with.
    path = Path(doc.file_path).resolve()
    uploads_root = settings.UPLOADS_DIR.resolve()
    if path.is_relative_to(uploads_root) and path.exists():
        path.unlink()
    # Remove from knowledge base index
    remove_document(doc.id)
    db.delete(doc)
    db.commit()

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.database import get_db, Base
from app.models.document import Document
from app.models.project import Project
from app.models.task import Task, TaskPriority
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    # Background knowledge indexing would touch the real KB; disable it here.
    monkeypatch.setattr("app.routers.documents.ingest_document", lambda *a, **k: None)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client, db, uploads
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _upload(client, filename="report.txt", content=b"hello document", content_type="text/plain", **extra):
    files = {"file": (filename, content, content_type)}
    return client.post("/documents/upload", files=files, data=extra or None)


# ----------------------------------------------------------------------
# Upload validation
# ----------------------------------------------------------------------
def test_upload_valid_file(client):
    test_client, db, uploads = client

    response = _upload(test_client)

    assert response.status_code == 201
    doc = response.json()
    assert doc["original_filename"] == "report.txt"
    assert doc["file_size_bytes"] == len(b"hello document")
    assert doc["title"] == "report.txt"
    assert (uploads / doc["filename"]).exists()


def test_upload_rejects_empty_filename(client):
    test_client, db, uploads = client

    response = test_client.post(
        "/documents/upload",
        files={"file": ("", b"data", "text/plain")},
    )

    # FastAPI may reject the nameless file part during multipart parsing (422)
    # before our endpoint runs; either way it is a graceful client error, not a 500.
    assert response.status_code in (400, 422)


def test_upload_rejects_disallowed_type(client):
    test_client, db, uploads = client

    response = _upload(test_client, filename="malware.exe", content=b"MZ", content_type="application/x-msdownload")

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_upload_rejects_nonexistent_project(client):
    test_client, db, uploads = client

    response = _upload(test_client, project_id="9999")

    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


def test_upload_accepts_existing_project(client):
    test_client, db, uploads = client

    project = Project(name="BAJA HV", category="baja", status="active")
    db.add(project)
    db.commit()
    db.refresh(project)

    response = _upload(test_client, project_id=str(project.id))

    assert response.status_code == 201
    assert response.json()["project_id"] == project.id


def test_upload_rejects_oversized_file(client, monkeypatch):
    test_client, db, uploads = client

    monkeypatch.setattr("app.routers.documents.MAX_UPLOAD_SIZE_BYTES", 10)

    response = _upload(test_client, content=b"x" * 1024)

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    # Aborted upload must not leave a partial file behind.
    assert list(uploads.iterdir()) == []


# ----------------------------------------------------------------------
# Download / view
# ----------------------------------------------------------------------
def test_download_valid_document(client):
    test_client, db, uploads = client

    upload = _upload(test_client, filename="spec.pdf", content=b"%PDF-1.4 fake", content_type="application/pdf")
    doc_id = upload.json()["id"]

    response = test_client.get(f"/documents/{doc_id}/download")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake"
    assert response.headers["content-type"].startswith("application/pdf")
    assert "spec.pdf" in response.headers.get("content-disposition", "")


def test_download_missing_document(client):
    test_client, db, uploads = client

    response = test_client.get("/documents/9999/download")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_download_missing_physical_file(client):
    test_client, db, uploads = client

    upload = _upload(test_client)
    doc_id = upload.json()["id"]
    doc = db.query(Document).filter(Document.id == doc_id).first()
    (uploads / doc.filename).unlink()

    response = test_client.get(f"/documents/{doc_id}/download")

    assert response.status_code == 404
    assert "missing on disk" in response.json()["detail"]


def test_download_rejects_path_traversal(client, tmp_path):
    test_client, db, uploads = client

    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    doc = Document(
        filename="evil.txt",
        original_filename="evil.txt",
        file_path=str(outside),
        mime_type="text/plain",
        file_size_bytes=6,
        title="evil",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    response = test_client.get(f"/documents/{doc.id}/download")

    assert response.status_code == 404
    assert "outside the uploads directory" in response.json()["detail"]


# ----------------------------------------------------------------------
# Deletion safety
# ----------------------------------------------------------------------
def test_delete_document_removes_file_within_uploads(client):
    test_client, db, uploads = client

    upload = _upload(test_client)
    doc_id = upload.json()["id"]
    doc = db.query(Document).filter(Document.id == doc_id).first()
    stored = uploads / doc.filename
    assert stored.exists()

    response = test_client.delete(f"/documents/{doc_id}")

    assert response.status_code == 204
    assert not stored.exists()
    assert db.query(Document).filter(Document.id == doc_id).first() is None


def test_delete_document_never_deletes_outside_uploads(client, tmp_path):
    """A tampered document row must never cause a delete outside uploads."""
    test_client, db, uploads = client

    outside = tmp_path / "precious.txt"
    outside.write_text("do not delete")
    doc = Document(
        filename="evil.txt",
        original_filename="evil.txt",
        file_path=str(outside),
        mime_type="text/plain",
        file_size_bytes=14,
        title="evil",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    response = test_client.delete(f"/documents/{doc.id}")

    assert response.status_code == 204
    assert outside.exists()
    assert db.query(Document).filter(Document.id == doc.id).first() is None
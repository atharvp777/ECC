"""AI Chat project-document context tests.

The chat context must include project document metadata, and content questions
must pull the project's document text on demand (scoped to the project, never
leaking documents from other projects). Extraction reuses the existing
``knowledge_service.extract_text_from_file`` — PDF text extraction is already
supported via PyPDF2.
"""
import pytest
from unittest.mock import patch, MagicMock

from app.services.ai_service import (
    _build_context,
    _project_document_context,
    _identify_document_project,
    chat_with_ai,
)
from app.models.project import Project
from app.models.document import Document
from app.core.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _seed_insem_with_doc(db, tmp_path, content="Data Science and Visualization course."):
    proj = Project(name="In-SEM", description="Insem 7th Sem", category="college", status="ACTIVE")
    db.add(proj)
    db.commit()
    db.refresh(proj)
    f = tmp_path / "syllabus.txt"
    f.write_text(content)
    doc = Document(
        filename="syllabus.txt",
        original_filename="BE SEM 1 Syllabus.pdf",
        file_path=str(f),
        mime_type="text/plain",
        file_size_bytes=f.stat().st_size,
        title="BE SEM 1 Syllabus",
        project_id=proj.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(proj)
    return proj


def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


# ----------------------------------------------------------------------
# Metadata in the main chat context
# ----------------------------------------------------------------------
def test_build_context_includes_project_documents(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path)
    ctx = _build_context(db_session)
    assert "In-SEM" in ctx
    assert "Documents: BE SEM 1 Syllabus" in ctx
    assert "Description: Insem 7th Sem" in ctx


def test_build_context_project_without_documents_shows_no_doc_part(db_session):
    proj = Project(name="BAJA HV", category="baja", status="ACTIVE")
    db_session.add(proj)
    db_session.commit()
    ctx = _build_context(db_session)
    assert "BAJA HV" in ctx
    assert "Documents:" not in ctx


# ----------------------------------------------------------------------
# Content retrieval (project-scoped, on demand)
# ----------------------------------------------------------------------
def test_project_document_context_extracts_project_doc_text(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path, content="Subjects: Data Science and Visualization.")
    result = _project_document_context(
        db_session,
        [{"role": "user", "content": "What is the BE SEM 1 syllabus about?"}],
    )
    assert "PROJECT DOCUMENT CONTENTS (In-SEM)" in result
    assert "BE SEM 1 Syllabus" in result
    assert "Data Science and Visualization" in result


def test_project_document_context_fuzzy_project_name(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path)
    for question in (
        "what does the insem project document contain",
        "Summarize the syllabus in my In-SEM project.",
        "What are the subjects in the semester project?",
    ):
        result = _project_document_context(
            db_session,
            [{"role": "user", "content": question}],
        )
        assert "PROJECT DOCUMENT CONTENTS (In-SEM)" in result, question


def test_project_document_context_follow_up_resolves_from_history(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path)
    messages = [
        {"role": "user", "content": "what's the document in my insem project"},
        {"role": "assistant", "content": "In-SEM has BE SEM 1 Syllabus.pdf."},
        {"role": "user", "content": "what is this document about?"},
    ]
    result = _project_document_context(db_session, messages)
    assert "PROJECT DOCUMENT CONTENTS (In-SEM)" in result


def test_project_document_context_listing_question_skips_text(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path)
    result = _project_document_context(
        db_session,
        [{"role": "user", "content": "What documents are in my In-SEM project?"}],
    )
    assert result == ""


def test_project_document_context_no_project_no_text(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path)
    result = _project_document_context(
        db_session,
        [{"role": "user", "content": "What is the weather like today?"}],
    )
    assert result == ""


def test_project_document_context_project_without_docs_returns_empty(db_session, tmp_path):
    proj = Project(name="BAJA HV", category="baja", status="ACTIVE")
    db_session.add(proj)
    db_session.commit()
    result = _project_document_context(
        db_session,
        [{"role": "user", "content": "Summarize the BAJA document."}],
    )
    assert result == ""


def test_project_document_context_missing_file_graceful(db_session, tmp_path):
    proj = Project(name="In-SEM", category="college", status="ACTIVE")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)
    doc = Document(
        filename="missing.pdf",
        original_filename="Missing.pdf",
        file_path=str(tmp_path / "does-not-exist.pdf"),
        mime_type="application/pdf",
        file_size_bytes=0,
        title="Missing",
        project_id=proj.id,
    )
    db_session.add(doc)
    db_session.commit()
    result = _project_document_context(
        db_session,
        [{"role": "user", "content": "What does the BE SEM 1 syllabus contain?"}],
    )
    assert result != ""
    assert "text could not be extracted" in result


def test_project_document_context_does_not_leak_other_projects(db_session, tmp_path):
    insem = _seed_insem_with_doc(db_session, tmp_path, content="In-SEM secret syllabus content.")
    baja = Project(name="BAJA HV", description="eBAJA electric vehicle", category="baja", status="ACTIVE")
    db_session.add(baja)
    db_session.commit()
    db_session.refresh(baja)

    # Ask about the OTHER project, which has its own document.
    f = tmp_path / "baja.txt"
    f.write_text("Brake bias and suspension tuning.")
    doc = Document(
        filename="baja.txt",
        original_filename="BAJA notes.txt",
        file_path=str(f),
        mime_type="text/plain",
        file_size_bytes=f.stat().st_size,
        title="BAJA notes",
        project_id=baja.id,
    )
    db_session.add(doc)
    db_session.commit()

    result = _project_document_context(
        db_session,
        [{"role": "user", "content": "What is the BAJA document about?"}],
    )
    assert "BAJA" in result
    assert "In-SEM secret syllabus content" not in result


def test_identify_project_fuzzy_variants(db_session):
    proj = Project(name="In-SEM", description="Insem 7th Sem", category="college", status="ACTIVE")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)
    for phrase in ("my insem project", "In-SEM", "in sem", "the semester project"):
        assert _identify_document_project(db_session, phrase) == proj, phrase


# ----------------------------------------------------------------------
# End-to-end through chat_with_ai (fallback LLM path, mocked)
# ----------------------------------------------------------------------
def test_chat_with_ai_includes_document_text_in_prompt(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path, content="Exam dates: 10 December and 12 December.")
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            "The BE SEM 1 syllabus exam dates are 10 and 12 December."
        )
        mock_groq.return_value = mock_client

        reply = chat_with_ai(
            [{"role": "user", "content": "What is the BE SEM 1 syllabus about?"}],
            db_session,
        )

    assert reply == "The BE SEM 1 syllabus exam dates are 10 and 12 December."
    sent_prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "PROJECT DOCUMENT CONTENTS (In-SEM)" in sent_prompt
    assert "Exam dates: 10 December" in sent_prompt


def test_chat_with_ai_listing_question_uses_metadata_only(db_session, tmp_path):
    proj = _seed_insem_with_doc(db_session, tmp_path, content="Secret in-document text.")
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            "In-SEM has one document: BE SEM 1 Syllabus.pdf."
        )
        mock_groq.return_value = mock_client

        reply = chat_with_ai(
            [{"role": "user", "content": "What documents are in my In-SEM project?"}],
            db_session,
        )

    assert "BE SEM 1 Syllabus" in reply
    sent_prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "Documents: BE SEM 1 Syllabus" in sent_prompt
    assert "PROJECT DOCUMENT CONTENTS" not in sent_prompt
    assert "Secret in-document text" not in sent_prompt
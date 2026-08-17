"""Regression tests for safe handling of a missing/empty/corrupt knowledge index.

Covers the bug where `DELETE /documents/{id}` returned 500 because
`_load_index()` called `json.loads()` on an empty `chunks.json`.
"""
import json
import pytest

from app.services import knowledge_service


@pytest.fixture
def index_files(monkeypatch, tmp_path):
    chunks_file = tmp_path / "chunks.json"
    tfidf_file = tmp_path / "tfidf.json"
    monkeypatch.setattr(knowledge_service, "CHUNKS_FILE", chunks_file)
    monkeypatch.setattr(knowledge_service, "TFIDF_FILE", tfidf_file)
    return chunks_file, tfidf_file


def test_load_index_missing_files(index_files):
    chunks_file, tfidf_file = index_files
    assert not chunks_file.exists() and not tfidf_file.exists()
    chunks, idf = knowledge_service._load_index()
    assert chunks == []
    assert idf == {}


def test_load_index_empty_files(index_files):
    chunks_file, tfidf_file = index_files
    chunks_file.write_text("")
    tfidf_file.write_text("")
    chunks, idf = knowledge_service._load_index()
    assert chunks == []
    assert idf == {}


def test_load_index_whitespace_only_files(index_files):
    chunks_file, tfidf_file = index_files
    chunks_file.write_text("   \n\t ")
    tfidf_file.write_text("  \n")
    chunks, idf = knowledge_service._load_index()
    assert chunks == []
    assert idf == {}


def test_load_index_valid_json(index_files):
    chunks_file, tfidf_file = index_files
    expected_chunks = [
        {"id": "abc123", "doc_id": 1, "title": "Doc", "start": 0, "text": "hello world"},
    ]
    expected_idf = {"hello": 1.0, "world": 1.0}
    chunks_file.write_text(json.dumps(expected_chunks))
    tfidf_file.write_text(json.dumps(expected_idf))
    chunks, idf = knowledge_service._load_index()
    assert chunks == expected_chunks
    assert idf == expected_idf


def test_load_index_valid_json_legacy_cp1252_encoding(index_files):
    # Older versions wrote the index with the platform default encoding
    # (cp1252 on Windows), so non-ASCII chunk text is not valid UTF-8.
    chunks_file, tfidf_file = index_files
    expected_chunks = [
        {"id": "abc123", "doc_id": 1, "title": "Caf\u00e9", "start": 0, "text": "na\u00efve r\u00e9sum\u00e9"},
    ]
    chunks_file.write_bytes(json.dumps(expected_chunks).encode("cp1252"))
    tfidf_file.write_bytes(b"{}")
    chunks, idf = knowledge_service._load_index()
    assert chunks == expected_chunks
    assert idf == {}


def test_load_index_malformed_json(index_files):
    chunks_file, tfidf_file = index_files
    chunks_file.write_text("{ this is not valid json ")
    tfidf_file.write_text('{"ok": ')
    chunks, idf = knowledge_service._load_index()
    assert chunks == []
    assert idf == {}


def test_load_index_wrong_top_level_type(index_files):
    chunks_file, tfidf_file = index_files
    chunks_file.write_text('"just a string"')
    tfidf_file.write_text("[1, 2, 3]")
    chunks, idf = knowledge_service._load_index()
    assert chunks == []
    assert idf == {}


def test_remove_document_missing_index_no_crash(index_files):
    remove_document = knowledge_service.remove_document
    assert remove_document(99) is None


def test_remove_document_empty_index_no_crash(index_files):
    chunks_file, tfidf_file = index_files
    chunks_file.write_text("")
    tfidf_file.write_text("")
    assert knowledge_service.remove_document(99) is None


def test_remove_document_malformed_index_no_crash(index_files):
    chunks_file, tfidf_file = index_files
    chunks_file.write_text("not json at all")
    tfidf_file.write_text("")
    assert knowledge_service.remove_document(99) is None


def test_remove_document_valid_index_keeps_other_docs(index_files):
    chunks_file, tfidf_file = index_files
    original = [
        {"id": "a", "doc_id": 1, "title": "One", "start": 0, "text": "alpha beta"},
        {"id": "b", "doc_id": 2, "title": "Two", "start": 0, "text": "gamma delta"},
    ]
    chunks_file.write_text(json.dumps(original))
    tfidf_file.write_text(json.dumps({}))
    knowledge_service.remove_document(1)
    remaining, _ = knowledge_service._load_index()
    assert remaining == [original[1]]


# ----------------------------------------------------------------------
# extract_text_from_file — robustness across missing/empty/malformed files
# ----------------------------------------------------------------------
def test_extract_missing_file_returns_empty(tmp_path):
    assert knowledge_service.extract_text_from_file(
        str(tmp_path / "nope.pdf"), "application/pdf"
    ) == ""


def test_extract_unsupported_mime_returns_empty(tmp_path):
    f = tmp_path / "notes.docx"
    f.write_bytes(b"PK")
    assert knowledge_service.extract_text_from_file(str(f), "application/zip") == ""


def test_extract_malformed_pdf_returns_failure_marker(tmp_path):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"%PDF-1.4 not a real pdf at all")
    text = knowledge_service.extract_text_from_file(str(f), "application/pdf")
    assert text.startswith("[PDF extraction failed")


def test_extract_empty_pdf_returns_empty(tmp_path):
    # An empty file is not a valid PDF; PyPDF2 raises, which is surfaced as a
    # failure marker — never a crash.
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    text = knowledge_service.extract_text_from_file(str(f), "application/pdf")
    assert text == "" or text.startswith("[PDF extraction failed")


def test_extract_text_plain_clips_to_max_chars(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("word " * 2000)  # ~10KB
    text = knowledge_service.extract_text_from_file(str(f), "text/plain", max_chars=100)
    assert len(text) == 100
    assert text == ("word " * 2000)[:100]


def test_extract_text_plain_unlimited_when_max_zero(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("word " * 100)
    text = knowledge_service.extract_text_from_file(str(f), "text/plain", max_chars=0)
    assert len(text) == len("word " * 100)


def test_extract_text_markdown_supported(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Title\n\nbody text")
    text = knowledge_service.extract_text_from_file(str(f), "text/markdown")
    assert "Title" in text and "body text" in text


def test_extract_docx_malformed_returns_failure_marker(tmp_path):
    f = tmp_path / "bad.docx"
    f.write_bytes(b"this is not a docx")
    text = knowledge_service.extract_text_from_file(
        str(f),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert text.startswith("[DOCX extraction failed")
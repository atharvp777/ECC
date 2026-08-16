"""
Knowledge Base service — chunk docs, embed locally with TF-IDF, search with cosine similarity.
For Q&A answers, uses Groq (free).

No OpenAI needed at all.
"""

import json
import math
import re
import hashlib
import logging
from pathlib import Path
from collections import Counter
from typing import Optional

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.note import Note
from app.models.document import Document

logger = logging.getLogger(__name__)

INDEX_DIR   = settings.KNOWLEDGE_DIR / "faiss_index"
CHUNKS_FILE = INDEX_DIR / "chunks.json"
TFIDF_FILE  = INDEX_DIR / "tfidf.json"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE    = 400
CHUNK_OVERLAP = 50
TOP_K         = 5

# Common English stop words – used to focus keyword matching on meaningful terms
_STOP_WORDS = {
    "the","is","can","you","my","what","for","about","of","in","on","at","by","and",
    "or","to","we","our","have","has","had","do","does","did","will","would","should",
    "could","may","might","must","i","me","myself","we","our","ours","ourselves",
    "you","your","yours","yourself","yourselves","he","him","his","himself",
    "she","her","hers","herself","it","its","itself","they","them","their","theirs",
    "themselves","this","that","these","those","am","are","was","were","be","been",
    "being","a","an","as","if","then","once","here","there","when","where","why",
    "how","all","any","both","each","few","more","most","other","some","such",
    "no","nor","not","only","own","same","so","than","too","very","just","now"
}

# ── Text extraction ───────────────────────────────────────────────────────────
def extract_text_from_file(file_path: str, mime_type: str) -> str:
    path = Path(file_path)
    if not path.exists():
        return ""
    if mime_type == "application/pdf":
        try:
            import PyPDF2
            text = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        text.append(t)
            return "\n".join(text)
        except Exception as e:
            return f"[PDF extraction failed: {e}]"
    if mime_type in ("text/plain", "text/markdown"):
        return path.read_text(encoding="utf-8", errors="replace")
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            import docx
            doc = docx.Document(path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            return f"[DOCX extraction failed: {e}]"
    return ""


# ── Chunking ──────────────────────────────────────────────────────────────────
def _chunk_text(text: str, doc_id: int, doc_title: str) -> list[dict]:
    words = text.split()
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for i in range(0, len(words), step):
        chunk_words = words[i: i + CHUNK_SIZE]
        chunk_text  = " ".join(chunk_words)
        chunk_id    = hashlib.md5(f"{doc_id}:{i}".encode()).hexdigest()[:8]
        chunks.append({"id": chunk_id, "doc_id": doc_id, "title": doc_title, "start": i, "text": chunk_text})
    return chunks


# ── TF-IDF vectorizer (local, no API) ────────────────────────────────────────
def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b[a-z]{2,}\b', text.lower())


def _build_tfidf(chunks: list[dict]) -> dict:
    """Build IDF scores over all chunks."""
    N = len(chunks)
    if N == 0:
        return {}
    df = Counter()
    for chunk in chunks:
        tokens = set(_tokenize(chunk["text"]))
        for t in tokens:
            df[t] += 1
    idf = {t: math.log((N + 1) / (cnt + 1)) + 1 for t, cnt in df.items()}
    return idf


def _tfidf_vec(text: str, idf: dict) -> dict[str, float]:
    tokens = _tokenize(text)
    tf = Counter(tokens)
    total = max(len(tokens), 1)
    vec = {}
    for t, cnt in tf.items():
        if t in idf:
            vec[t] = (cnt / total) * idf[t]
    return vec


def _cosine(a: dict, b: dict) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot  = sum(a[t] * b[t] for t in common)
    na   = math.sqrt(sum(v * v for v in a.values()))
    nb   = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb + 1e-9)


# ── Persistence ───────────────────────────────────────────────────────────────
def _load_index() -> tuple[list[dict], dict]:
    """Load the persisted knowledge index.

    Missing, empty or corrupt index files are treated as an empty index so the
    rest of the pipeline never crashes on bad on-disk state.
    """
    def _read_json(path: Path, expected_type) -> object | None:
        if not path.exists():
            return None
        try:
            raw_bytes = path.read_bytes()
        except OSError:
            return None
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # Files written by older versions used the platform default
            # encoding (cp1252 on Windows). Decoding as latin-1 never fails
            # and round-trips those bytes faithfully.
            raw = raw_bytes.decode("latin-1")
        if not raw.strip():
            return None
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Knowledge index file %s is corrupt; treating it as empty.", path)
            return None
        if not isinstance(value, expected_type):
            logger.warning("Knowledge index file %s has an unexpected format; treating it as empty.", path)
            return None
        return value

    chunks = _read_json(CHUNKS_FILE, list) or []
    idf    = _read_json(TFIDF_FILE, dict)  or {}
    return chunks, idf


def _save_index(chunks: list[dict], idf: dict):
    CHUNKS_FILE.write_text(json.dumps(chunks, ensure_ascii=False))
    TFIDF_FILE.write_text(json.dumps(idf,    ensure_ascii=False))


# ── Public API ────────────────────────────────────────────────────────────────
def ingest_document(doc_id: int, doc_title: str, file_path: str, mime_type: str) -> int:
    text = extract_text_from_file(file_path, mime_type)
    if not text.strip():
        return 0
    new_chunks = _chunk_text(text, doc_id, doc_title)
    if not new_chunks:
        return 0
    chunks, _ = _load_index()
    chunks = [c for c in chunks if c["doc_id"] != doc_id]  # remove old version
    chunks.extend(new_chunks)
    idf = _build_tfidf(chunks)
    _save_index(chunks, idf)
    return len(new_chunks)


def remove_document(doc_id: int):
    if not CHUNKS_FILE.exists():
        return
    chunks, _ = _load_index()
    chunks = [c for c in chunks if c["doc_id"] != doc_id]
    idf = _build_tfidf(chunks)
    _save_index(chunks, idf)


def search_documents(query: str, top_k: int = TOP_K) -> list[dict]:
    chunks, idf = _load_index()
    if not chunks or not idf:
        return []
    q_vec = _tfidf_vec(query, idf)
    if not q_vec:
        return []
    scored = []
    for chunk in chunks:
        c_vec = _tfidf_vec(chunk["text"], idf)
        score = _cosine(q_vec, c_vec)
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"score": s, "doc_id": c["doc_id"], "title": c["title"], "text": c["text"]}
            for s, c in scored[:top_k] if s > 0]


def answer_from_docs(question: str) -> dict:
    """
    Returns a dict with two keys:
        - "answer": the generated answer string
        - "sources": list of document titles used as context (may be empty)

    Behaviour:
      * If GROQ_API_KEY is missing, returns a friendly warning.
      * Searches the TF‑IDF knowledge base for relevant chunks.
      * If relevant chunks are found, they are inserted into the prompt as context.
      * If no chunks are found, an empty‑context prompt is used – the model is
        instructed not to fabricate information.
      * If a project is identified from the question, its related information
        (description, tasks, notes, documents) is added to the context.
      * Calls Groq, handling any unexpected errors gracefully.
      * Always returns the same structure expected by the frontend.
    """
    # -----------------------------------------------------------------------
    # 1️⃣  Guard‑clause when the Groq key is not configured
    # -----------------------------------------------------------------------
    if not settings.GROQ_API_KEY:
        return {"answer": "⚠ Groq API key not configured.", "sources": []}

    # -----------------------------------------------------------------------
    # 2️⃣  Retrieve relevant document chunks
    # -----------------------------------------------------------------------
    chunks = search_documents(question)
    context = ""
    sources: list[str] = []

    if chunks:
        # Build a readable context string from the retrieved chunks
        context = "\n\n---\n\n".join(
            f"[Source: {c['title']}]\n{c['text']}" for c in chunks
        )
        sources = list({c["title"] for c in chunks})
    else:
        # No relevant chunks – still proceed, but make it clear that context is empty
        context = "(No document context provided.)"
        sources = []

    # -----------------------------------------------------------------------
    # 3️⃣  Identify a project that the question likely refers to
    # -----------------------------------------------------------------------
    db = SessionLocal()
    try:
        # Tokenise the question and drop stop‑words
        q_tokens = {t for t in re.findall(r'\b\w+\b', question.lower()) if t not in _STOP_WORDS}

        best_proj = None
        best_score = 0

        for proj in db.query(Project).all():
            # Tokenise project name and description
            name_tokens = set(re.findall(r'\b\w+\b', proj.name.lower()))
            desc_tokens = set(re.findall(r'\b\w+\b', (proj.description or "").lower()))

            # Score = 2 × matches in name + matches in description
            score = len(q_tokens & name_tokens) * 2 + len(q_tokens & desc_tokens)

            if score > best_score:
                best_score = score
                best_proj = proj

        if best_proj:
            # ---- Build project‑specific context ----
            proj_ctx = f"Project: {best_proj.name}"
            if best_proj.description:
                proj_ctx += f" – Description: {best_proj.description}"
            # (Project has no `tags` field – skip it)

            # ---- Retrieve related tasks (exclude DONE) ----
            tasks = (
                db.query(Task)
                .filter(
                    Task.project_id == best_proj.id,
                    Task.status != TaskStatus.DONE,
                )
                .order_by(Task.priority.asc(), Task.deadline.asc())
                .limit(3)
                .all()
            )
            if tasks:
                proj_ctx += "\n\nRelated Tasks:\n" + "\n".join(
                    f"- {t.title or 'Untitled'}" for t in tasks
                )

            # ---- Retrieve up to 3 notes ----
            notes = db.query(Note).filter(Note.project_id == best_proj.id).limit(3).all()
            if notes:
                proj_ctx += "\n\nRelated Notes:\n" + "\n".join(
                    f"- {n.title or 'Untitled'}" for n in notes
                )

            # ---- Retrieve up to 3 documents ----
            docs = db.query(Document).filter(Document.project_id == best_proj.id).limit(3).all()
            if docs:
                proj_ctx += "\n\nRelated Documents:\n" + "\n".join(
                    f"- {d.title or 'Untitled'}" for d in docs
                )

            # ---- Prepend project context to any existing document context ----
            if context:
                context = proj_ctx + "\n\n" + context
            else:
                context = proj_ctx
    finally:
        db.close()

    # -----------------------------------------------------------------------
    # 4️⃣  Build the prompt for Groq
    # -----------------------------------------------------------------------
    # The model is told explicitly that the context may be empty and must not be invented.
    prompt = f"""Answer the question using ONLY the document excerpts below.
If the answer isn't in the documents, you may answer from general knowledge,
but you must clearly state when you are not using any document context.

{context}

QUESTION: {question}

ANSWER:"""

    # -----------------------------------------------------------------------
    # 5️⃣  Call Groq with robust error handling
    # -----------------------------------------------------------------------
    try:
        from groq import Groq
        client = Groq(api_key=settings.GROQ_API_KEY)
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.2,
        )
        answer = response.choices[0].message.content.strip()
    except Exception:
        # Any unexpected error (network, API limit, etc.) – return a safe fallback
        answer = "Sorry, I couldn't generate a response right now."

    # -----------------------------------------------------------------------
    # 6️⃣  Return the structure the frontend expects
    # -----------------------------------------------------------------------
    return {"answer": answer, "sources": sources}

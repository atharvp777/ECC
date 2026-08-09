"""
Knowledge Base service — chunk docs, embed locally with TF-IDF, search with cosine similarity.
For Q&A answers, uses Groq (free).

No OpenAI needed at all.
"""

import json
import math
import re
import hashlib
from pathlib import Path
from collections import Counter
from typing import Optional

from app.core.config import settings

INDEX_DIR   = settings.KNOWLEDGE_DIR / "faiss_index"
CHUNKS_FILE = INDEX_DIR / "chunks.json"
TFIDF_FILE  = INDEX_DIR / "tfidf.json"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE    = 400
CHUNK_OVERLAP = 50
TOP_K         = 5


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
    chunks = json.loads(CHUNKS_FILE.read_text()) if CHUNKS_FILE.exists() else []
    idf    = json.loads(TFIDF_FILE.read_text())  if TFIDF_FILE.exists()  else {}
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
    # Fallback for development when the Groq key is not configured
    if not settings.GROQ_API_KEY:
        return {"answer": "I'm currently unavailable (no Groq key).", "sources": []}

    if not settings.GROQ_API_KEY:
        return {"answer": "⚠ Groq API key not configured.", "sources": []}

    chunks = search_documents(question)
    if not chunks:
        return {"answer": "No relevant documents found. Upload some files first.", "sources": []}

    context = "\n\n---\n\n".join(
        f"[Source: {c['title']}]\n{c['text']}" for c in chunks
    )
    prompt = f"""Answer the question using ONLY the document excerpts below.
If the answer isn't in the documents, say so clearly.

DOCUMENTS:
{context}

QUESTION: {question}

ANSWER:"""

    from groq import Groq
    client   = Groq(api_key=settings.GROQ_API_KEY)
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
        temperature=0.2,
    )
    sources = list({c["title"] for c in chunks})
    return {"answer": response.choices[0].message.content, "sources": sources}

import { useEffect, useState, useRef } from "react";
import { getDocuments, uploadDocument, deleteDocument, getProjects, searchDocs, askDocs, ingestDoc, indexStatus } from "../api";
import { Upload, Trash2, FileText, FileImage, File, Search, MessageSquare, RefreshCw, X } from "lucide-react";

const ICONS = {
  "application/pdf": FileText,
  "image/png": FileImage,
  "image/jpeg": FileImage,
};

function FileIcon({ type }) {
  const Icon = ICONS[type] || File;
  return <Icon size={20} color="var(--accent)" />;
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function SearchPanel({ onClose }) {
  const [query, setQuery]     = useState("");
  const [mode, setMode]       = useState("ask");   // "ask" | "search"
  const [result, setResult]   = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true); setResult(null);
    try {
      if (mode === "ask") {
        const r = await askDocs(query);
        setResult({ type: "ask", ...r });
      } else {
        const chunks = await searchDocs(query, 5);
        setResult({ type: "search", chunks });
      }
    } catch {
      setResult({ type: "error", answer: "Failed — is the backend running and OpenAI key set?" });
    } finally { setLoading(false); }
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", backdropFilter: "blur(4px)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 16, padding: 24, width: 640, maxWidth: "90vw", maxHeight: "80vh",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <button className={`btn btn-sm ${mode === "ask" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("ask")}>
              <MessageSquare size={12} /> Ask AI
            </button>
            <button className={`btn btn-sm ${mode === "search" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("search")}>
              <Search size={12} /> Semantic Search
            </button>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={14} /></button>
        </div>

        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 12 }}>
          {mode === "ask"
            ? "Ask a question and get a GPT-4o answer grounded in your uploaded documents."
            : "Find the most relevant chunks across all your documents by semantic meaning."}
        </div>

        {/* Input */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <input className="form-input" style={{ flex: 1 }}
            value={query} onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && run()}
            placeholder={mode === "ask" ? "What are the HV insulation requirements?" : "battery management system"}
            autoFocus />
          <button className="btn btn-primary" onClick={run} disabled={loading || !query.trim()}>
            {loading ? "…" : mode === "ask" ? "Ask" : "Search"}
          </button>
        </div>

        {/* Results */}
        <div style={{ overflowY: "auto", flex: 1 }}>
          {loading && <div className="spinner" />}

          {result?.type === "ask" && (
            <div>
              <div style={{
                background: "var(--surface2)", border: "1px solid var(--border)",
                borderRadius: 10, padding: 16, fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap",
              }}>
                {result.answer}
              </div>
              {result.sources?.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
                  Sources: {result.sources.join(" · ")}
                </div>
              )}
            </div>
          )}

          {result?.type === "search" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {result.chunks.length === 0
                ? <div className="empty"><p>No relevant chunks found. Try different keywords.</p></div>
                : result.chunks.map((c, i) => (
                  <div key={i} style={{
                    background: "var(--surface2)", border: "1px solid var(--border)",
                    borderRadius: 8, padding: 12,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)" }}>{c.title}</span>
                      <span style={{ fontSize: 11, color: "var(--muted)" }}>score: {c.score.toFixed(3)}</span>
                    </div>
                    <p style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>{c.text.slice(0, 300)}…</p>
                  </div>
                ))
              }
            </div>
          )}

          {result?.type === "error" && (
            <div style={{ color: "var(--danger)", fontSize: 13 }}>{result.answer}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Documents() {
  const [docs, setDocs]           = useState([]);
  const [projects, setProjects]   = useState([]);
  const [uploading, setUploading] = useState(false);
  const [projectFilter, setProjectFilter] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [status, setStatus]       = useState(null);
  const [reingesting, setReingesting] = useState(null);
  const inputRef = useRef();

  const load = async () => {
    try {
      const params = projectFilter ? { project_id: projectFilter } : {};
      const [d, p, s] = await Promise.all([getDocuments(params), getProjects(), indexStatus().catch(() => null)]);
      setDocs(d); setProjects(p); setStatus(s);
    } catch {}
  };

  useEffect(() => { load(); }, [projectFilter]);

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (projectFilter) fd.append("project_id", projectFilter);
      await uploadDocument(fd);
      load();
    } catch (err) {
      alert("Upload failed: " + (err.response?.data?.detail || err.message));
    } finally { setUploading(false); e.target.value = ""; }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this document?")) return;
    await deleteDocument(id); load();
  };

  const handleReingest = async (id) => {
    setReingesting(id);
    try { await ingestDoc(id); setTimeout(load, 1500); }
    finally { setReingesting(null); }
  };

  const projectName = (id) => projects.find(p => p.id === id)?.name || "—";

  return (
    <div className="page">
      {/* Header */}
      <div className="section-header">
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Knowledge Base</h2>
          {status && (
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
              {status.indexed_chunks} chunks indexed across {status.documents.length} documents
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <select className="form-select" style={{ width: "auto" }} value={projectFilter} onChange={e => setProjectFilter(e.target.value)}>
            <option value="">All Projects</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={() => setShowSearch(true)}>
            <Search size={14} /> Search Docs
          </button>
          <input ref={inputRef} type="file" style={{ display: "none" }} onChange={handleUpload}
            accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg" />
          <button className="btn btn-primary" onClick={() => inputRef.current.click()} disabled={uploading}>
            <Upload size={14} /> {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>

      {/* Tip banner */}
      <div style={{
        background: "rgba(79,124,255,.08)", border: "1px solid rgba(79,124,255,.2)",
        borderRadius: 10, padding: "10px 14px", marginBottom: 16, fontSize: 12, color: "var(--muted)",
      }}>
        💡 After uploading, documents are indexed automatically. Then ask questions in <strong style={{ color: "var(--accent)" }}>Search Docs</strong> or in AI Chat using keywords like "rulebook", "requirement", or "specification".
      </div>

      {/* Document list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {docs.map(doc => {
          const isIndexed = status?.documents?.some(d => d.doc_id === doc.id);
          return (
            <div key={doc.id} className="card card-sm" style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <FileIcon type={doc.mime_type} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {doc.title || doc.original_filename}
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <span>{fmtSize(doc.file_size_bytes)}</span>
                  <span>·</span>
                  <span>{doc.mime_type.split("/")[1]?.toUpperCase()}</span>
                  {doc.project_id && <><span>·</span><span>📁 {projectName(doc.project_id)}</span></>}
                  <span>·</span>
                  <span>{new Date(doc.created_at).toLocaleDateString()}</span>
                  <span>·</span>
                  <span style={{ color: isIndexed ? "var(--success)" : "var(--warning)" }}>
                    {isIndexed ? "✓ indexed" : "⏳ pending"}
                  </span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 4 }}>
                {!isIndexed && (
                  <button className="btn btn-ghost btn-sm" title="Re-index" onClick={() => handleReingest(doc.id)} disabled={reingesting === doc.id}>
                    <RefreshCw size={12} style={{ animation: reingesting === doc.id ? "spin .6s linear infinite" : "none" }} />
                  </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(doc.id)}><Trash2 size={12} /></button>
              </div>
            </div>
          );
        })}
        {docs.length === 0 && (
          <div className="empty" style={{ marginTop: 40 }}>
            <File size={40} style={{ margin: "0 auto 12px", display: "block", opacity: .3 }} />
            <p>No documents yet.</p>
            <p style={{ marginTop: 4, fontSize: 12 }}>Upload your eBAJA rulebook, AgroVault datasheets, or any PDF.</p>
          </div>
        )}
      </div>

      {showSearch && <SearchPanel onClose={() => setShowSearch(false)} />}
    </div>
  );
}


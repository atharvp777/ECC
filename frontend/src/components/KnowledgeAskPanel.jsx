import { useEffect, useRef, useState } from "react";
import { X, Sparkles, Search, Send } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import OrbitSkeleton from "./ui/OrbitSkeleton";
import { askDocs, searchDocs } from "../api";

/**
 * Knowledge panel for the Knowledge Library. Two clearly separated tools that
 * use the existing knowledge endpoints:
 *  - "Ask Orbit" — full RAG answer via askDocs (answer + sources).
 *  - "Search knowledge" — raw semantic chunks via searchDocs.
 * This is metadata-free semantic access, distinct from client-side filtering.
 */
export default function KnowledgeAskPanel({ onClose, triggerRef }) {
  const [mode, setMode] = useState("ask");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const closeBtnRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    closeBtnRef.current?.focus();
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !document.querySelector(".modal-overlay")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    return () => {
      triggerRef?.current?.focus?.();
    };
  }, [triggerRef]);

  const run = async () => {
    const q = query.trim();
    if (!q || loading) return;
    setLoading(true);
    setResult(null);
    try {
      if (mode === "ask") {
        const r = await askDocs(q);
        setResult({ type: "ask", ...r });
      } else {
        const chunks = await searchDocs(q, 5);
        setResult({ type: "search", chunks });
      }
    } catch {
      setResult({
        type: "error",
        message: "Couldn't reach the knowledge service. Check that the backend is running.",
      });
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (next) => {
    setMode(next);
    setResult(null);
  };

  return (
    <div className="task-drawer-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-drawer knowledge-panel" role="dialog" aria-modal="true" aria-label="Ask Orbit">
        <div className="task-drawer__header">
          <h3 className="task-drawer__title">Ask Orbit</h3>
          <button
            ref={closeBtnRef}
            type="button"
            className="task-drawer__icon-btn"
            onClick={onClose}
            aria-label="Close Ask Orbit"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="task-drawer__body">
          <p className="knowledge-panel__subtitle">
            Ask questions about your uploaded engineering knowledge, or search it semantically.
          </p>

          <div className="knowledge-modes" role="group" aria-label="Knowledge tool">
            <button
              type="button"
              className={`knowledge-mode${mode === "ask" ? " is-active" : ""}`}
              aria-pressed={mode === "ask"}
              onClick={() => switchMode("ask")}
            >
              <Sparkles size={13} aria-hidden="true" /> Ask Orbit
            </button>
            <button
              type="button"
              className={`knowledge-mode${mode === "search" ? " is-active" : ""}`}
              aria-pressed={mode === "search"}
              onClick={() => switchMode("search")}
            >
              <Search size={13} aria-hidden="true" /> Search knowledge
            </button>
          </div>

          <div className="knowledge-composer">
            <input
              ref={inputRef}
              className="orbit-input knowledge-composer__input"
              placeholder={mode === "ask" ? "What do I have documented about battery safety?" : "battery management system"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
              aria-label={mode === "ask" ? "Ask a question about your documents" : "Search your documents"}
            />
            <OrbitButton variant="primary" onClick={run} loading={loading} disabled={!query.trim()}>
              <Send size={13} aria-hidden="true" /> {mode === "ask" ? "Ask" : "Search"}
            </OrbitButton>
          </div>

          <div className="knowledge-results">
            {loading && (
              <div className="knowledge-results__loading" role="status" aria-label="Thinking">
                <OrbitSkeleton width="100%" height={14} shape="text" />
                <OrbitSkeleton width="92%" height={14} shape="text" />
                <OrbitSkeleton width="70%" height={14} shape="text" />
              </div>
            )}

            {result?.type === "ask" && (
              <div>
                <div className="knowledge-answer">{result.answer}</div>
                {result.sources?.length > 0 && (
                  <div className="knowledge-sources">
                    Sources: {result.sources.join(" · ")}
                  </div>
                )}
              </div>
            )}

            {result?.type === "search" && (
              result.chunks.length === 0 ? (
                <p className="knowledge-empty">No relevant chunks found. Try different keywords.</p>
              ) : (
                <div className="knowledge-chunks">
                  {result.chunks.map((c, i) => (
                    <div className="knowledge-chunk" key={i}>
                      <div className="knowledge-chunk__head">
                        <span className="knowledge-chunk__title">{c.title}</span>
                        <span className="knowledge-chunk__score">score: {Number(c.score).toFixed(3)}</span>
                      </div>
                      <p className="knowledge-chunk__text">{String(c.text || "").slice(0, 300)}…</p>
                    </div>
                  ))}
                </div>
              )
            )}

            {result?.type === "error" && (
              <p className="task-drawer__error" role="alert">{result.message}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
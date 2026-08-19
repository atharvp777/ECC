import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import Modal from "./Modal";
import OrbitSkeleton from "./ui/OrbitSkeleton";
import { isImage, isPdf, isPlainText } from "../utils/documents";

/**
 * Preview modal for a single document. Fetches the file bytes on demand (only
 * when the preview is opened — never for hover/list rendering) and renders
 * images inline, PDFs in the browser viewer, and text as plain text. When a
 * type can't be previewed, Download stays the primary action.
 */
export default function DocumentPreview({ doc, downloadUrl, onClose }) {
  const [state, setState] = useState({
    loading: true,
    kind: null,
    url: null,
    text: null,
    error: null,
  });
  const name = doc.title || doc.original_filename || "Document";

  useEffect(() => {
    let objectUrl = null;
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch(downloadUrl);
        if (!res.ok) throw new Error("preview load failed");
        const blob = await res.blob();
        if (cancelled) return;

        if (isPlainText(doc.mime_type)) {
          const text = await blob.text();
          if (cancelled) return;
          setState({ loading: false, kind: "text", text, url: null, error: null });
        } else if (isImage(doc.mime_type)) {
          objectUrl = URL.createObjectURL(blob);
          setState({ loading: false, kind: "image", url: objectUrl, text: null, error: null });
        } else if (isPdf(doc.mime_type)) {
          objectUrl = URL.createObjectURL(blob);
          setState({ loading: false, kind: "pdf", url: objectUrl, text: null, error: null });
        } else {
          setState({ loading: false, kind: "unsupported", url: null, text: null, error: null });
        }
      } catch {
        if (!cancelled) {
          setState({ loading: false, kind: null, url: null, text: null, error: "Couldn't load a preview for this document." });
        }
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [downloadUrl, doc.mime_type]);

  return (
    <Modal title={name} onClose={onClose}>
      <div className="doc-preview">
        {state.loading ? (
          <div className="doc-preview__loading" role="status" aria-label="Loading preview">
            <OrbitSkeleton width="100%" height={16} shape="text" />
            <OrbitSkeleton width="100%" height={220} />
            <OrbitSkeleton width="60%" height={14} shape="text" />
          </div>
        ) : state.error ? (
          <div className="doc-preview__fallback">
            <p>{state.error}</p>
            <a className="orbit-btn orbit-btn--primary" href={downloadUrl}>
              <Download size={14} aria-hidden="true" /> Download instead
            </a>
          </div>
        ) : state.kind === "image" ? (
          <img className="doc-preview__image" src={state.url} alt={name} />
        ) : state.kind === "pdf" ? (
          <iframe className="doc-preview__frame" src={state.url} title={name} />
        ) : state.kind === "text" ? (
          <pre className="doc-preview__text">{state.text}</pre>
        ) : (
          <div className="doc-preview__fallback">
            <p>Preview isn't available for this file type. Use Download to open the original.</p>
            <a className="orbit-btn orbit-btn--primary" href={downloadUrl}>
              <Download size={14} aria-hidden="true" /> Download
            </a>
          </div>
        )}
      </div>
    </Modal>
  );
}
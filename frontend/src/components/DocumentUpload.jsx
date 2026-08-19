import { useEffect, useRef, useState } from "react";
import { X, Upload } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import { uploadDocument } from "../api";

/**
 * Upload drawer for the Knowledge Library. Supports click-to-browse and
 * drag-and-drop, an optional project association, a submitting state that
 * blocks duplicate submission, and honest inline errors that keep the form
 * open on failure.
 */
export default function DocumentUpload({ projects, onClose, onUploaded, triggerRef }) {
  const [file, setFile] = useState(null);
  const [projectId, setProjectId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const closeBtnRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    closeBtnRef.current?.focus();
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

  const submit = async () => {
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (projectId) fd.append("project_id", projectId);
      await uploadDocument(fd);
      onUploaded();
    } catch (err) {
      setError(err?.response?.data?.detail || "Couldn't upload the document.");
      setUploading(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) setFile(f);
  };

  return (
    <div className="task-drawer-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-drawer doc-upload" role="dialog" aria-modal="true" aria-label="Upload document">
        <div className="task-drawer__header">
          <h3 className="task-drawer__title">Upload document</h3>
          <button
            ref={closeBtnRef}
            type="button"
            className="task-drawer__icon-btn"
            onClick={onClose}
            aria-label="Close upload dialog"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="task-drawer__body">
          {error && (
            <p className="task-drawer__error" role="alert">
              {error}
            </p>
          )}

          <label
            className={`doc-upload__drop${dragging ? " doc-upload__drop--drag" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="visually-hidden"
              accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp"
              aria-label="Choose file to upload"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <Upload size={20} className="doc-upload__drop-icon" aria-hidden="true" />
            {file ? (
              <span className="doc-upload__filename">{file.name}</span>
            ) : (
              <span className="doc-upload__hint">Drag &amp; drop a document here, or click to browse</span>
            )}
            <span className="doc-upload__types">PDF · TXT · MD · DOCX · PNG · JPG · WEBP (up to 50 MB)</span>
          </label>

          {file && (
            <button
              type="button"
              className="doc-upload__remove"
              onClick={() => {
                setFile(null);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
            >
              Remove file
            </button>
          )}

          <div className="doc-upload__field">
            <span className="doc-upload__label" id="doc-upload-project-label">
              Project (optional)
            </span>
            <select
              className="orbit-input"
              aria-labelledby="doc-upload-project-label"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">No project</option>
              {projects.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="doc-upload__actions">
            <OrbitButton variant="ghost" onClick={onClose}>
              Cancel
            </OrbitButton>
            <OrbitButton variant="primary" onClick={submit} loading={uploading} disabled={!file}>
              {uploading ? "Uploading…" : "Upload document"}
            </OrbitButton>
          </div>
        </div>
      </div>
    </div>
  );
}
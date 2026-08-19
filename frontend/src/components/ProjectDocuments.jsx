import { useRef, useState } from "react";
import { FileText, Upload, Download, Trash2 } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import OrbitEmptyState from "./ui/OrbitEmptyState";
import { getDocumentDownloadUrl } from "../api";
import { formatShortDate } from "../utils/format";

const MIME_LABELS = {
  "application/pdf": "PDF",
  "text/plain": "TXT",
  "text/markdown": "MD",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "image/png": "PNG",
  "image/jpeg": "JPG",
  "image/webp": "WEBP",
};

function typeLabel(mime) {
  if (MIME_LABELS[mime]) return MIME_LABELS[mime];
  const part = String(mime || "").split("/").pop();
  return part ? part.toUpperCase() : "FILE";
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Scoped documents view for a project workspace. Reuses the existing document
 * API for listing/upload/download/delete; not the future global Document Library.
 */
export default function ProjectDocuments({ docs, onUpload, onDelete }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  const handleChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      await onUpload(file);
    } catch {
      setUploadError("Couldn't upload the document.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  return (
    <div className="project-documents">
      {uploadError && (
        <div className="tasks-notice tasks-notice--error" role="alert">{uploadError}</div>
      )}
      <div className="project-documents__toolbar">
        <OrbitButton variant="secondary" onClick={() => inputRef.current?.click()} loading={uploading}>
          <Upload size={14} aria-hidden="true" /> Upload document
        </OrbitButton>
      </div>
      <input
        ref={inputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleChange}
        accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp"
        aria-label="Upload document"
      />
      {docs.length === 0 ? (
        <OrbitEmptyState
          icon={FileText}
          title="No documents yet."
          description="Upload PDFs, text, Markdown, DOCX, or images to keep reference material with this project."
        />
      ) : (
        <div className="project-documents__list">
          {docs.map((doc) => (
            <div key={doc.id} className="project-documents__row">
              <FileText size={16} className="project-documents__icon" aria-hidden="true" />
              <div className="project-documents__main">
                <div className="project-documents__name">{doc.title || doc.original_filename}</div>
                <div className="project-documents__meta">
                  <span className="project-documents__type">{typeLabel(doc.mime_type)}</span>
                  <span>{fmtSize(doc.file_size_bytes)}</span>
                  <span>{formatShortDate(doc.created_at)}</span>
                </div>
              </div>
              <a
                className="task-action-btn"
                href={getDocumentDownloadUrl(doc.id)}
                title="Download"
                aria-label={`Download ${doc.title || doc.original_filename}`}
              >
                <Download size={13} aria-hidden="true" />
              </a>
              <button
                type="button"
                className="task-action-btn task-action-btn--danger"
                title="Delete document"
                aria-label={`Delete ${doc.title || doc.original_filename}`}
                onClick={() => onDelete(doc)}
              >
                <Trash2 size={13} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
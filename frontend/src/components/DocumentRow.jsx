import { FileText, FileImage, File, Download, Eye, Trash2, RefreshCw } from "lucide-react";
import OrbitBadge from "./ui/OrbitBadge";
import { docTypeLabel, fmtBytes, isImage } from "../utils/documents";
import { formatShortDate } from "../utils/format";

function DocIcon({ mime }) {
  if (isImage(mime)) return <FileImage size={15} aria-hidden="true" />;
  if (mime === "application/pdf") return <FileText size={15} aria-hidden="true" />;
  return <File size={15} aria-hidden="true" />;
}

/**
 * Dense presentational row for the Knowledge Library.
 *
 * `status` is one of "ready" | "pending" | null (null hides the badge).
 * Row actions never render backend errors here; errors live at page level.
 */
export default function DocumentRow({
  doc,
  projectName = "No project",
  status,
  downloadUrl,
  onPreview,
  onDelete,
  onReindex,
  reindexing = false,
}) {
  const name = doc.title || doc.original_filename || "Untitled document";

  return (
    <div className="doc-row">
      <span className="doc-row__icon">
        <DocIcon mime={doc.mime_type} />
      </span>

      <div className="doc-row__main">
        <div className="doc-row__name" title={name}>
          {name}
        </div>
        <div className="doc-row__meta">
          <span className="doc-row__project">{projectName}</span>
          <span className="doc-row__type">{docTypeLabel(doc.mime_type)}</span>
          <span>{fmtBytes(doc.file_size_bytes)}</span>
          <span>{formatShortDate(doc.created_at)}</span>
        </div>
      </div>

      {status && (
        <OrbitBadge variant={status === "ready" ? "success" : "warning"}>
          {status === "ready" ? "Ready" : "Pending"}
        </OrbitBadge>
      )}

      <div className="doc-row__actions">
        {status === "pending" && onReindex && (
          <button
            type="button"
            className="task-action-btn"
            title="Re-index document"
            aria-label={`Re-index ${name}`}
            onClick={() => onReindex(doc)}
            disabled={reindexing}
          >
            <RefreshCw size={13} className={reindexing ? "doc-row__spin" : ""} aria-hidden="true" />
          </button>
        )}
        {onPreview && (
          <button
            type="button"
            className="task-action-btn"
            title="Preview document"
            aria-label={`Preview ${name}`}
            onClick={() => onPreview(doc)}
          >
            <Eye size={13} aria-hidden="true" />
          </button>
        )}
        <a
          className="task-action-btn"
          href={downloadUrl}
          title="Download"
          aria-label={`Download ${name}`}
        >
          <Download size={13} aria-hidden="true" />
        </a>
        <button
          type="button"
          className="task-action-btn task-action-btn--danger"
          title="Delete document"
          aria-label={`Delete ${name}`}
          onClick={() => onDelete(doc)}
        >
          <Trash2 size={13} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
/** MIME → short label map for document file types. */
export const DOC_MIME_LABELS = {
  "application/pdf": "PDF",
  "text/plain": "TXT",
  "text/markdown": "MD",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "image/png": "PNG",
  "image/jpeg": "JPG",
  "image/webp": "WEBP",
};

/** Human label for a document's MIME type ("PDF", "TXT", "FILE", ...). */
export function docTypeLabel(mime) {
  if (DOC_MIME_LABELS[mime]) return DOC_MIME_LABELS[mime];
  const part = String(mime || "").split("/").pop();
  return part ? part.toUpperCase() : "FILE";
}

/** Compact byte size like "1.2 MB". Returns "—" when unset. */
export function fmtBytes(bytes) {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** True for image MIME types (PNG/JPG/WEBP). */
export function isImage(mime) {
  return /^image\//.test(mime || "");
}

/** True for PDFs. */
export function isPdf(mime) {
  return mime === "application/pdf";
}

/** True for plain-text/markdown documents that render inline as text. */
export function isPlainText(mime) {
  return mime === "text/plain" || mime === "text/markdown";
}
import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Sparkles, SearchX, Upload } from "lucide-react";
import {
  getDocuments,
  getProjects,
  deleteDocument,
  ingestDoc,
  indexStatus,
  getDocumentDownloadUrl,
} from "../api";
import OrbitButton from "../components/ui/OrbitButton";
import OrbitEmptyState from "../components/ui/OrbitEmptyState";
import OrbitSkeleton from "../components/ui/OrbitSkeleton";
import Modal from "../components/Modal";
import DocumentRow from "../components/DocumentRow";
import DocumentFilters from "../components/DocumentFilters";
import DocumentUpload from "../components/DocumentUpload";
import DocumentPreview from "../components/DocumentPreview";
import KnowledgeAskPanel from "../components/KnowledgeAskPanel";
import { docTypeLabel } from "../utils/documents";

/**
 * Knowledge Library — the global Documents page redesigned as an
 * engineering knowledge workspace. Client-side metadata search/filters
 * compose against the already-loaded list; semantic access stays separated
 * in the Ask Orbit panel.
 */
export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [projects, setProjects] = useState([]);
  const [indexed, setIndexed] = useState(null); // { docIds, chunks, loaded }
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const [uploadOpen, setUploadOpen] = useState(false);
  const [previewDoc, setPreviewDoc] = useState(null);
  const [askOpen, setAskOpen] = useState(false);
  const [deleteDoc, setDeleteDoc] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [reindexing, setReindexing] = useState(null);

  const [notice, setNotice] = useState(null);
  const noticeTimer = useRef(null);

  const uploadBtnRef = useRef(null);
  const askBtnRef = useRef(null);

  const load = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [d, p, s] = await Promise.all([
        getDocuments(),
        getProjects(),
        indexStatus().catch(() => null),
      ]);
      setDocs(d);
      setProjects(p);
      setIndexed(
        s
          ? { docIds: new Set(s.documents.map((x) => x.doc_id)), chunks: s.indexed_chunks, loaded: true }
          : null
      );
      setLoading(false);
    } catch {
      setLoading(false);
      setLoadError(true);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => () => clearTimeout(noticeTimer.current), []);

  const showNotice = (text, kind = "success") => {
    setNotice({ text, kind });
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 4000);
  };

  const projectName = (id) => projects.find((p) => p.id === id)?.name || "No project";

  const typeOptions = useMemo(() => {
    const set = new Set(docs.map((d) => docTypeLabel(d.mime_type)));
    return [...set].sort();
  }, [docs]);

  const filtered = docs.filter((doc) => {
    const name = (doc.title || doc.original_filename || "").toLowerCase();
    const proj = projectName(doc.project_id).toLowerCase();
    const type = docTypeLabel(doc.mime_type);
    const q = search.trim().toLowerCase();
    const matchesSearch = !q || name.includes(q) || proj.includes(q) || type.toLowerCase().includes(q);
    const matchesProject = !projectFilter || String(doc.project_id) === projectFilter;
    const matchesType = !typeFilter || type === typeFilter;
    return matchesSearch && matchesProject && matchesType;
  });

  const filtersActive = Boolean(search.trim() || projectFilter || typeFilter);

  const clearFilters = () => {
    setSearch("");
    setProjectFilter("");
    setTypeFilter("");
  };

  const handleUploaded = () => {
    setUploadOpen(false);
    showNotice("Document uploaded");
    load();
  };

  const confirmDelete = async () => {
    if (!deleteDoc || deleting) return;
    setDeleting(true);
    try {
      await deleteDocument(deleteDoc.id);
      setDeleteDoc(null);
      setDeleting(false);
      showNotice("Document deleted");
      load();
    } catch {
      setDeleteDoc(null);
      setDeleting(false);
      showNotice("Couldn't delete the document.", "error");
    }
  };

  const handleReindex = async (doc) => {
    setReindexing(doc.id);
    try {
      await ingestDoc(doc.id);
      load();
    } catch {
      showNotice("Couldn't re-index the document.", "error");
    } finally {
      setReindexing(null);
    }
  };

  return (
    <div className="page">
      <header className="doc-header">
        <div>
          <h1 className="orbit-title doc-header__title">Knowledge Library</h1>
          <p className="doc-header__subtitle">Your engineering knowledge, organized by project.</p>
        </div>
      </header>

      {notice && (
        <div className={`tasks-notice tasks-notice--${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.text}
        </div>
      )}

      <div className="doc-toolbar">
        <DocumentFilters
          search={search}
          onSearch={setSearch}
          projectFilter={projectFilter}
          onProjectFilter={setProjectFilter}
          typeFilter={typeFilter}
          onTypeFilter={setTypeFilter}
          projects={projects}
          types={typeOptions}
        />
        <div className="doc-toolbar__actions">
          <OrbitButton
            ref={uploadBtnRef}
            variant="primary"
            onClick={() => setUploadOpen(true)}
            aria-haspopup="dialog"
          >
            <Upload size={14} aria-hidden="true" /> Upload document
          </OrbitButton>
          <OrbitButton
            ref={askBtnRef}
            variant="secondary"
            onClick={() => setAskOpen(true)}
            aria-haspopup="dialog"
          >
            <Sparkles size={14} aria-hidden="true" /> Ask Orbit
          </OrbitButton>
        </div>
      </div>

      <div className="doc-summary">
        <span className="doc-summary__count">
          {filtered.length} {filtered.length === 1 ? "document" : "documents"}
          {indexed?.loaded && indexed.chunks > 0 && (
            <span className="doc-summary__chunks">· {indexed.chunks} chunks indexed</span>
          )}
        </span>
        {filtersActive && (
          <div className="doc-summary__filters">
            {search.trim() && <span className="doc-summary__filter">“{search.trim()}”</span>}
            {projectFilter && <span className="doc-summary__filter">{projectName(Number(projectFilter))}</span>}
            {typeFilter && <span className="doc-summary__filter">{typeFilter}</span>}
            <button type="button" className="doc-summary__clear" onClick={clearFilters}>
              Clear filters
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <div className="doc-list" role="status" aria-label="Loading documents">
          {Array.from({ length: 6 }).map((_, i) => (
            <div className="doc-row doc-row--skeleton" key={i}>
              <OrbitSkeleton width={30} height={30} shape="circle" />
              <div className="doc-row__main">
                <OrbitSkeleton width="45%" height={14} shape="text" />
                <OrbitSkeleton width="65%" height={11} shape="text" />
              </div>
              <OrbitSkeleton width={64} height={20} />
              <OrbitSkeleton width={120} height={24} />
            </div>
          ))}
        </div>
      ) : loadError ? (
        <OrbitEmptyState
          icon={SearchX}
          title="Couldn't load documents."
          description="Check that the backend is running, then try again."
          action={
            <OrbitButton variant="primary" onClick={load}>
              Retry
            </OrbitButton>
          }
        />
      ) : docs.length === 0 ? (
        <OrbitEmptyState
          icon={BookOpen}
          title="Your knowledge library is empty."
          description="Upload your first engineering document to get started."
          action={
            <OrbitButton variant="primary" onClick={() => setUploadOpen(true)}>
              <Upload size={14} aria-hidden="true" /> Upload a document
            </OrbitButton>
          }
        />
      ) : filtered.length === 0 ? (
        <OrbitEmptyState
          icon={SearchX}
          title="No documents match your filters."
          description="Try adjusting your search or filters."
          action={
            <OrbitButton variant="secondary" onClick={clearFilters}>
              Clear filters
            </OrbitButton>
          }
        />
      ) : (
        <div className="doc-list">
          {filtered.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              projectName={projectName(doc.project_id)}
              status={indexed?.loaded ? (indexed.docIds.has(doc.id) ? "ready" : "pending") : null}
              downloadUrl={getDocumentDownloadUrl(doc.id)}
              reindexing={reindexing === doc.id}
              onPreview={setPreviewDoc}
              onReindex={handleReindex}
              onDelete={setDeleteDoc}
            />
          ))}
        </div>
      )}

      {uploadOpen && (
        <DocumentUpload
          projects={projects}
          onClose={() => setUploadOpen(false)}
          onUploaded={handleUploaded}
          triggerRef={uploadBtnRef}
        />
      )}
      {previewDoc && (
        <DocumentPreview
          doc={previewDoc}
          downloadUrl={getDocumentDownloadUrl(previewDoc.id)}
          onClose={() => setPreviewDoc(null)}
        />
      )}
      {askOpen && <KnowledgeAskPanel onClose={() => setAskOpen(false)} triggerRef={askBtnRef} />}
      {deleteDoc && (
        <Modal title="Delete document?" onClose={() => setDeleteDoc(null)}>
          <p className="confirm-text">"{deleteDoc.title || deleteDoc.original_filename}"</p>
          <p className="confirm-hint">This cannot be undone.</p>
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteDoc(null)}>
              Cancel
            </OrbitButton>
            <OrbitButton variant="danger" loading={deleting} onClick={confirmDelete}>
              Delete
            </OrbitButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
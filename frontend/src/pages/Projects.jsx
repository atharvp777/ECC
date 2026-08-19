import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getProjects, deleteProject } from "../api";
import { Plus, FolderKanban } from "lucide-react";
import OrbitButton from "../components/ui/OrbitButton";
import OrbitSkeleton from "../components/ui/OrbitSkeleton";
import OrbitEmptyState from "../components/ui/OrbitEmptyState";
import Modal from "../components/Modal";
import ProjectRow from "../components/ProjectRow";
import ProjectDrawer from "../components/ProjectDrawer";

export default function Projects() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const [drawerMode, setDrawerMode] = useState(null); // "create" | project object
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [notice, setNotice] = useState(null);
  const triggerRef = useRef(null);

  const load = async () => {
    try {
      setProjects(await getProjects());
      setLoadError(false);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreate = (trigger) => {
    triggerRef.current = trigger || null;
    setDrawerMode("create");
  };

  const openEdit = (project, trigger) => {
    triggerRef.current = trigger || null;
    setDrawerMode(project);
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProject(deleteTarget.id);
      setDeleteTarget(null);
      setNotice("Project deleted");
      load();
    } catch {
      setDeleteError("Couldn't delete the project.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="page">
      {notice && (
        <div className="tasks-notice tasks-notice--success" role="status">
          {notice}
        </div>
      )}

      <div className="projects-header">
        <div>
          <h2 className="projects-header__title">Projects</h2>
          <p className="projects-header__subtitle">Keep your work organized.</p>
        </div>
        <OrbitButton variant="primary" onClick={(e) => openCreate(e.currentTarget)}>
          <Plus size={14} aria-hidden="true" /> New project
        </OrbitButton>
      </div>

      {loading ? (
        <div className="projects-load" aria-hidden="true">
          {Array.from({ length: 5 }).map((_, i) => (
            <OrbitSkeleton key={i} width="100%" height={64} />
          ))}
        </div>
      ) : loadError ? (
        <div className="overview-error" role="alert">
          <p>Couldn't load projects.</p>
          <OrbitButton size="sm" variant="secondary" onClick={load}>Retry</OrbitButton>
        </div>
      ) : projects.length === 0 ? (
        <OrbitEmptyState
          icon={FolderKanban}
          title="No projects yet."
          description="Create your first project."
          action={
            <OrbitButton variant="secondary" onClick={() => openCreate(null)}>
              <Plus size={14} aria-hidden="true" /> New project
            </OrbitButton>
          }
        />
      ) : (
        <div className="projects-list">
          {projects.map((project) => (
            <ProjectRow
              key={project.id}
              project={project}
              onOpen={(p) => navigate(`/projects/${p.id}`)}
              onEdit={(p) => openEdit(p, null)}
              onDelete={(p) => setDeleteTarget(p)}
            />
          ))}
        </div>
      )}

      {drawerMode && (
        <ProjectDrawer
          project={drawerMode === "create" ? null : drawerMode}
          triggerRef={triggerRef}
          onClose={() => setDrawerMode(null)}
          onSaved={() => {
            setDrawerMode(null);
            setNotice(drawerMode === "create" ? "Project created" : "Project saved");
            load();
          }}
        />
      )}

      {deleteTarget && (
        <Modal title="Delete project?" onClose={() => setDeleteTarget(null)}>
          <p className="confirm-text">"{deleteTarget.name}"</p>
          <p className="confirm-hint">This deletes the project and all of its tasks, notes, and documents.</p>
          {deleteError && <p className="overview-action-error" role="alert">{deleteError}</p>}
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteTarget(null)}>Cancel</OrbitButton>
            <OrbitButton variant="danger" onClick={confirmDelete} loading={deleting}>Delete</OrbitButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
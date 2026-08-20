import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import {
  getProject, getTasks, getProjects,
  updateTask, deleteTask,
  getDocuments, uploadDocument, deleteDocument,
  getNotes, createNote, updateNote, deleteNote,
  getProjectContext, createProjectContext, updateProjectContext, deleteProjectContext,
} from "../api";
import { ArrowLeft, Pencil, Plus, Sparkles, Trash2, FolderKanban } from "lucide-react";
import OrbitButton from "../components/ui/OrbitButton";
import OrbitSkeleton from "../components/ui/OrbitSkeleton";
import OrbitEmptyState from "../components/ui/OrbitEmptyState";
import Modal from "../components/Modal";
import ProjectTabs from "../components/ProjectTabs";
import ProjectOverview from "../components/ProjectOverview";
import ProjectTasks from "../components/ProjectTasks";
import ProjectDocuments from "../components/ProjectDocuments";
import ProjectNotes from "../components/ProjectNotes";
import ProjectContext from "../components/ProjectContext";
import ProjectAi from "../components/ProjectAi";
import ProjectDrawer from "../components/ProjectDrawer";
import TaskDrawer from "../components/TaskDrawer";
import {
  STATUS_LABELS,
  CATEGORY_LABELS,
  formatProjectDeadline,
} from "../utils/projects";

const TAB_BY_PATH = {
  tasks: "tasks",
  documents: "documents",
  notes: "notes",
  context: "context",
  ai: "ai",
};

function activeTabOf(pathname, id) {
  const rest = pathname.slice(`/projects/${id}`.length).replace(/^\/+/, "");
  return TAB_BY_PATH[rest] || "overview";
}

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const tab = activeTabOf(location.pathname, id);

  const [project, setProject] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [docs, setDocs] = useState([]);
  const [notes, setNotes] = useState([]);
  const [contextItems, setContextItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const [drawerId, setDrawerId] = useState(null);
  const [drawerInitialMode, setDrawerInitialMode] = useState("view");
  const [editingProject, setEditingProject] = useState(false);
  const [deleteTaskTarget, setDeleteTaskTarget] = useState(null);
  const [deleteDoc, setDeleteDoc] = useState(null);
  const [deleteNoteTarget, setDeleteNoteTarget] = useState(null);
  const [deleteContextTarget, setDeleteContextTarget] = useState(null);
  const [mutating, setMutating] = useState(false);
  const [notice, setNotice] = useState(null);
  const triggerRef = useRef(null);

  const loadAll = async () => {
    try {
      const [p, t, d, n, ctx, allProjects] = await Promise.all([
        getProject(id),
        getTasks({ project_id: id }),
        getDocuments({ project_id: id }),
        getNotes({ project_id: id }),
        getProjectContext(id),
        getProjects(),
      ]);
      const enriched = t.map((task) => ({
        ...task,
        project_name: allProjects.find((pr) => pr.id === task.project_id)?.name,
      }));
      setProject(p);
      setTasks(enriched);
      setDocs(d);
      setNotes(n);
      setContextItems(Array.isArray(ctx) ? ctx : []);
      setProjects(allProjects);
      setLoadError(false);
      setNotFound(false);
    } catch (err) {
      if (err?.response?.status === 404) setNotFound(true);
      else setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    setLoadError(false);
    setNotFound(false);
    setDrawerId(null);
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

  const openTask = (task, event) => {
    triggerRef.current = event?.currentTarget || null;
    setDrawerInitialMode("view");
    setDrawerId(task.id ?? task.task_id);
  };

  const openNewTask = (event) => {
    triggerRef.current = event?.currentTarget || null;
    setDrawerInitialMode("new");
    setDrawerId("new");
  };

  const handleComplete = async (task) => {
    if (mutating) return;
    const tid = task.id ?? task.task_id;
    const newStatus = task.status === "done" ? "todo" : "done";
    setMutating(true);
    try {
      await updateTask(tid, { status: newStatus });
      await loadAll();
      setNotice(newStatus === "done" ? "Task completed" : "Task reopened");
    } catch {
      setNotice("Couldn't update the task.");
    } finally {
      setMutating(false);
    }
  };

  const confirmDeleteTask = async () => {
    if (!deleteTaskTarget) return;
    try {
      await deleteTask(deleteTaskTarget.id);
      if (drawerId === deleteTaskTarget.id) setDrawerId(null);
      setDeleteTaskTarget(null);
      setNotice("Task deleted");
      loadAll();
    } catch {
      setDeleteTaskTarget(null);
      setNotice("Couldn't delete the task.");
    }
  };

  const handleUpload = async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("project_id", String(id));
    await uploadDocument(fd);
    await loadAll();
  };

  const confirmDeleteDoc = async () => {
    if (!deleteDoc) return;
    try {
      await deleteDocument(deleteDoc.id);
      setDeleteDoc(null);
      setNotice("Document deleted");
      loadAll();
    } catch {
      setDeleteDoc(null);
      setNotice("Couldn't delete the document.");
    }
  };

  const handleCreateNote = async () => {
    const note = await createNote({ title: "Untitled note", content: "", project_id: Number(id) });
    await loadAll();
    return note;
  };

  const handleUpdateNote = async (noteId, payload) => {
    await updateNote(noteId, payload);
    await loadAll();
  };

  const confirmDeleteNote = async () => {
    if (!deleteNoteTarget) return;
    try {
      await deleteNote(deleteNoteTarget.id);
      setDeleteNoteTarget(null);
      setNotice("Note deleted");
      loadAll();
    } catch {
      setDeleteNoteTarget(null);
      setNotice("Couldn't delete the note.");
    }
  };

  const handleCreateContext = async () => {
    const item = await createProjectContext(Number(id), { content: "" });
    await loadAll();
    return item;
  };

  const handleUpdateContext = async (itemId, payload) => {
    await updateProjectContext(Number(id), itemId, payload);
    await loadAll();
  };

  const confirmDeleteContext = async () => {
    if (!deleteContextTarget) return;
    try {
      await deleteProjectContext(Number(id), deleteContextTarget.id);
      setDeleteContextTarget(null);
      setNotice("Context fact deleted");
      loadAll();
    } catch {
      setDeleteContextTarget(null);
      setNotice("Couldn't delete the context fact.");
    }
  };

  const rowActions = (task) => (
    <>
      <button
        type="button"
        className="task-action-btn"
        title="Edit task"
        aria-label={`Edit ${task.title}`}
        onClick={() => openTask(task, null)}
      >
        <Pencil size={13} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="task-action-btn task-action-btn--danger"
        title="Delete task"
        aria-label={`Delete ${task.title}`}
        onClick={() => setDeleteTaskTarget(task)}
      >
        <Trash2 size={13} aria-hidden="true" />
      </button>
    </>
  );

  if (loading) {
    return (
      <div className="page">
        <div className="project-load">
          <OrbitSkeleton width="140px" height={22} shape="text" />
          <OrbitSkeleton width="260px" height={34} />
          <OrbitSkeleton width="100%" height={110} />
          <OrbitSkeleton width="100%" height={110} />
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="page">
        <OrbitEmptyState
          icon={FolderKanban}
          title="Project not found."
          description="This project may have been deleted, or the link is incorrect."
          action={
            <OrbitButton variant="secondary" onClick={() => navigate("/projects")}>
              <ArrowLeft size={14} aria-hidden="true" /> Back to Projects
            </OrbitButton>
          }
        />
      </div>
    );
  }

  if (loadError || !project) {
    return (
      <div className="page">
        <div className="overview-error" role="alert">
          <p>Couldn't load this project.</p>
          <OrbitButton size="sm" variant="secondary" onClick={() => { setLoading(true); loadAll(); }}>
            Retry
          </OrbitButton>
        </div>
      </div>
    );
  }

  const drawerTask = drawerId != null && drawerId !== "new" ? tasks.find((t) => t.id === drawerId) : null;

  return (
    <div className="page">
      {notice && (
        <div className="tasks-notice tasks-notice--success" role="status">
          {notice}
        </div>
      )}

      <button type="button" className="project-back" onClick={() => navigate("/projects")}>
        <ArrowLeft size={14} aria-hidden="true" /> Projects
      </button>

      <header className="project-workspace__header">
        <div className="project-workspace__identity">
          <span className="project-workspace__dot" style={{ background: project.color }} aria-hidden="true" />
          <h2 className="project-workspace__name">{project.name}</h2>
        </div>
        {project.description && <p className="project-workspace__desc">{project.description}</p>}
        <div className="project-workspace__meta">
          <span className="project-workspace__meta-item">
            {STATUS_LABELS[project.status] || project.status}
          </span>
          <span className="project-workspace__meta-item">
            {CATEGORY_LABELS[project.category] || project.category}
          </span>
          {formatProjectDeadline(project.deadline) && (
            <span className={`project-workspace__meta-item${formatProjectDeadline(project.deadline).startsWith("Overdue") ? " project-workspace__meta-item--overdue" : ""}`}>
              {formatProjectDeadline(project.deadline)}
            </span>
          )}
          <span className="project-workspace__meta-item">
            {project.task_count === 0 ? "No tasks yet" : `${project.done_tasks || 0} / ${project.task_count} completed`}
          </span>
        </div>

        <div className="project-workspace__actions">
          <OrbitButton size="sm" variant="secondary" onClick={() => setEditingProject(true)}>
            <Pencil size={12} aria-hidden="true" /> Edit
          </OrbitButton>
          <OrbitButton size="sm" variant="primary" onClick={openNewTask}>
            <Plus size={12} aria-hidden="true" /> Add task
          </OrbitButton>
          <OrbitButton size="sm" variant="ghost" onClick={() => navigate(`/projects/${id}/ai`)}>
            <Sparkles size={12} aria-hidden="true" /> Ask Orbit
          </OrbitButton>
        </div>
      </header>

      <ProjectTabs projectId={id} active={tab} />

      <div className="project-panel" role="tabpanel" id="project-panel" aria-labelledby={`project-tab-${tab}`}>
        {tab === "overview" && (
          <ProjectOverview
            project={project}
            tasks={tasks}
            docs={docs}
            notes={notes}
            onNavigate={(name) => navigate(`/projects/${id}${name === "overview" ? "" : `/${name}`}`)}
          />
        )}
        {tab === "tasks" && (
          <ProjectTasks
            tasks={tasks}
            onComplete={handleComplete}
            onOpenTask={openTask}
            actionsFor={rowActions}
            onNewTask={openNewTask}
          />
        )}
        {tab === "documents" && (
          <ProjectDocuments docs={docs} onUpload={handleUpload} onDelete={setDeleteDoc} />
        )}
        {tab === "notes" && (
          <ProjectNotes
            notes={notes}
            onCreate={handleCreateNote}
            onUpdate={handleUpdateNote}
            onDelete={setDeleteNoteTarget}
          />
        )}
        {tab === "context" && (
          <ProjectContext
            items={contextItems}
            onCreate={handleCreateContext}
            onUpdate={handleUpdateContext}
            onDelete={setDeleteContextTarget}
          />
        )}
        {tab === "ai" && <ProjectAi project={project} />}
      </div>

      {(drawerId === "new" || drawerTask) && (
        <TaskDrawer
          task={drawerTask}
          initialMode={drawerInitialMode}
          projects={projects}
          defaultProjectId={String(id)}
          onClose={() => setDrawerId(null)}
          onReload={loadAll}
          onCreated={() => {
            setDrawerId(null);
            setNotice("Task created");
            loadAll();
          }}
          onRequestDelete={(t) => setDeleteTaskTarget(t)}
          onAskOrbit={() => navigate(`/projects/${id}/ai`)}
          triggerRef={triggerRef}
        />
      )}

      {editingProject && (
        <ProjectDrawer
          project={project}
          onClose={() => setEditingProject(false)}
          onSaved={() => {
            setEditingProject(false);
            setNotice("Project saved");
            loadAll();
          }}
        />
      )}

      {deleteTaskTarget && (
        <Modal title="Delete task?" onClose={() => setDeleteTaskTarget(null)}>
          <p className="confirm-text">"{deleteTaskTarget.title}"</p>
          <p className="confirm-hint">This cannot be undone.</p>
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteTaskTarget(null)}>Cancel</OrbitButton>
            <OrbitButton variant="danger" onClick={confirmDeleteTask}>Delete</OrbitButton>
          </div>
        </Modal>
      )}

      {deleteDoc && (
        <Modal title="Delete document?" onClose={() => setDeleteDoc(null)}>
          <p className="confirm-text">"{deleteDoc.title || deleteDoc.original_filename}"</p>
          <p className="confirm-hint">This removes the file and its knowledge index entry.</p>
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteDoc(null)}>Cancel</OrbitButton>
            <OrbitButton variant="danger" onClick={confirmDeleteDoc}>Delete</OrbitButton>
          </div>
        </Modal>
      )}

      {deleteNoteTarget && (
        <Modal title="Delete note?" onClose={() => setDeleteNoteTarget(null)}>
          <p className="confirm-text">"{deleteNoteTarget.title || "Untitled note"}"</p>
          <p className="confirm-hint">This cannot be undone.</p>
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteNoteTarget(null)}>Cancel</OrbitButton>
            <OrbitButton variant="danger" onClick={confirmDeleteNote}>Delete</OrbitButton>
          </div>
        </Modal>
      )}

      {deleteContextTarget && (
        <Modal title="Delete this fact?" onClose={() => setDeleteContextTarget(null)}>
          <p className="confirm-text">"{deleteContextTarget.content}"</p>
          <p className="confirm-hint">Orbit will stop using it as project context.</p>
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteContextTarget(null)}>Cancel</OrbitButton>
            <OrbitButton variant="danger" onClick={confirmDeleteContext}>Delete</OrbitButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
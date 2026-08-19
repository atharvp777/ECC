import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getTasks, getProjects, updateTask, deleteTask } from "../api";
import { Plus, Search, X, Pencil, Trash2, Check, AlertTriangle } from "lucide-react";
import TaskRow from "../components/TaskRow";
import TaskGroup from "../components/TaskGroup";
import TaskFilters from "../components/TaskFilters";
import TaskDrawer from "../components/TaskDrawer";
import OrbitButton from "../components/ui/OrbitButton";
import OrbitSkeleton from "../components/ui/OrbitSkeleton";
import Modal from "../components/Modal";

const PRIORITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 };

const GROUPS = [
  ["overdue", "Overdue", true],
  ["today", "Today", false],
  ["upcoming", "Upcoming", false],
  ["no-deadline", "No deadline", false],
  ["completed", "Completed", false],
];

function groupOf(task) {
  if (task.status === "done") return "completed";
  if (!task.deadline) return "no-deadline";
  const deadline = new Date(task.deadline);
  if (deadline < new Date()) return "overdue";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day = new Date(deadline.getFullYear(), deadline.getMonth(), deadline.getDate());
  return day.getTime() === today.getTime() ? "today" : "upcoming";
}

function compareActive(a, b) {
  const ap = PRIORITY_RANK[a.priority] ?? 3;
  const bp = PRIORITY_RANK[b.priority] ?? 3;
  if (ap !== bp) return ap - bp;
  const at = a.deadline ? new Date(a.deadline).getTime() : Infinity;
  const bt = b.deadline ? new Date(b.deadline).getTime() : Infinity;
  if (at !== bt) return at - bt;
  return (a.id ?? a.task_id) - (b.id ?? b.task_id);
}

function compareCompleted(a, b) {
  const at = new Date(a.completed_at || a.updated_at || 0).getTime();
  const bt = new Date(b.completed_at || b.updated_at || 0).getTime();
  if (at !== bt) return bt - at;
  return (b.id ?? b.task_id) - (a.id ?? a.task_id);
}

export default function Tasks() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlProject = searchParams.get("project");

  const [tasks, setTasks] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [priority, setPriority] = useState("all");
  const [project, setProject] = useState(urlProject ? String(urlProject) : "all");
  const [type, setType] = useState("all");

  const [drawerId, setDrawerId] = useState(null);
  const [drawerInitialMode, setDrawerInitialMode] = useState("view");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [notice, setNotice] = useState(null);
  const [mutating, setMutating] = useState(false);
  const triggerRef = useRef(null);
  const noticeTimer = useRef(null);

  const load = async () => {
    try {
      const [t, p] = await Promise.all([getTasks(), getProjects()]);
      const enriched = t.map((task) => ({
        ...task,
        project_name: p.find((pr) => pr.id === task.project_id)?.name,
      }));
      setTasks(enriched);
      setProjects(p);
      setLoadError(false);
      return enriched;
    } catch {
      setLoadError(true);
      return [];
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => () => clearTimeout(noticeTimer.current), []);

  const showNotice = (kind, text) => {
    setNotice({ kind, text });
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 4000);
  };

  const openDrawer = (id, mode, trigger) => {
    triggerRef.current = trigger || null;
    setDrawerInitialMode(mode);
    setDrawerId(id);
  };

  const openTask = (task, event) => {
    openDrawer(task.id ?? task.task_id, "view", event?.currentTarget || null);
  };

  const handleComplete = async (task) => {
    if (mutating) return;
    const id = task.id ?? task.task_id;
    const newStatus = task.status === "done" ? "todo" : "done";
    setMutating(true);
    try {
      await updateTask(id, { status: newStatus });
      await load();
      showNotice("success", newStatus === "done" ? "Task completed" : "Task reopened");
    } catch {
      showNotice("error", "Couldn't update task.");
    } finally {
      setMutating(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    try {
      await deleteTask(id);
      if (drawerId === id) setDrawerId(null);
      setDeleteTarget(null);
      showNotice("success", "Task deleted");
      load();
    } catch {
      setDeleteTarget(null);
      showNotice("error", "Couldn't delete task");
    }
  };

  const resetFilters = () => {
    setQuery("");
    setStatus("all");
    setPriority("all");
    setProject(urlProject ? String(urlProject) : "all");
    setType("all");
  };

  const rowActions = (task) => (
    <>
      <button
        type="button"
        className="task-action-btn"
        title="Edit task"
        aria-label={`Edit ${task.title}`}
        onClick={() => openDrawer(task.id ?? task.task_id, "edit", null)}
      >
        <Pencil size={13} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="task-action-btn task-action-btn--danger"
        title="Delete task"
        aria-label={`Delete ${task.title}`}
        onClick={() => setDeleteTarget(task)}
      >
        <Trash2 size={13} aria-hidden="true" />
      </button>
    </>
  );

  const matches = (task) => {
    if (status === "active" && task.status === "done") return false;
    if (status === "completed" && task.status !== "done") return false;
    if (priority !== "all" && task.priority !== priority) return false;
    if (project !== "all" && String(task.project_id) !== project) return false;
    if (type !== "all" && (task.task_type || "work") !== type) return false;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      const haystack = `${task.title} ${task.description || ""} ${task.project_name || ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  };

  const emptyState = (title, desc) => (
    <div className="tasks-empty">
      <p className="tasks-empty__title">{title}</p>
      {desc && <p className="tasks-empty__desc">{desc}</p>}
    </div>
  );

  const renderGroups = () => {
    const filtered = tasks.filter(matches);
    if (filtered.length === 0) {
      if (status === "completed") return emptyState("No completed tasks yet.", null);
      if (status === "active") return emptyState("You're clear.", "No active tasks right now.");
      return emptyState("No matching tasks.", "Try a different search or clear filters.");
    }
    return (
      <>
        {GROUPS.map(([key, label, isOverdue]) => {
          const groupTasks = filtered.filter((t) => groupOf(t) === key);
          if (groupTasks.length === 0) return null;
          const sorted = [...groupTasks].sort(key === "completed" ? compareCompleted : compareActive);
          return (
            <TaskGroup
              key={key}
              label={label}
              overdue={isOverdue}
              tasks={sorted}
              onComplete={handleComplete}
              onOpen={openTask}
              actionsFor={rowActions}
            />
          );
        })}
      </>
    );
  };

  if (loading) {
    return (
      <div className="page">
        <div className="tasks-skeleton" aria-hidden="true">
          {Array.from({ length: 6 }).map((_, i) => (
            <OrbitSkeleton key={i} width="100%" height={44} />
          ))}
        </div>
      </div>
    );
  }

  const drawerTask = drawerId != null && drawerId !== "new" ? tasks.find((t) => t.id === drawerId) : null;
  const filtersActive = query !== "" || status !== "all" || priority !== "all" || project !== "all" || type !== "all";
  const newTaskTrigger = () => openDrawer("new", "new", null);

  return (
    <div className="page">
      {notice && (
        <div className={`tasks-notice tasks-notice--${notice.kind}`} role="status">
          {notice.kind === "success" ? (
            <Check size={14} aria-hidden="true" />
          ) : (
            <AlertTriangle size={14} aria-hidden="true" />
          )}
          {notice.text}
        </div>
      )}

      {loadError ? (
        <div className="overview-error" role="alert">
          <p>Couldn't load your tasks.</p>
          <OrbitButton size="sm" variant="secondary" onClick={load}>Retry</OrbitButton>
        </div>
      ) : (
        <>
          <div className="tasks-toolbar">
            <div className="tasks-search">
              <Search size={14} aria-hidden="true" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search tasks..."
                aria-label="Search tasks"
              />
              {query && (
                <button type="button" className="tasks-search__clear" onClick={() => setQuery("")} aria-label="Clear search">
                  <X size={12} aria-hidden="true" />
                </button>
              )}
            </div>
            <OrbitButton variant="primary" onClick={newTaskTrigger}>
              <Plus size={14} aria-hidden="true" /> New task
            </OrbitButton>
          </div>

          <TaskFilters
            status={status}
            priority={priority}
            project={project}
            type={type}
            projects={projects}
            active={filtersActive}
            onStatusChange={setStatus}
            onPriorityChange={setPriority}
            onProjectChange={setProject}
            onTypeChange={setType}
            onReset={resetFilters}
          />

          {tasks.length === 0 ? (
            <div className="tasks-empty">
              <p className="tasks-empty__title">No tasks yet.</p>
              <p className="tasks-empty__desc">Create your first task.</p>
              <OrbitButton variant="secondary" onClick={newTaskTrigger}>
                <Plus size={14} aria-hidden="true" /> New task
              </OrbitButton>
            </div>
          ) : (
            renderGroups()
          )}
        </>
      )}

      {(drawerId === "new" || drawerTask) && (
        <TaskDrawer
          task={drawerTask}
          initialMode={drawerInitialMode}
          projects={projects}
          defaultProjectId={project !== "all" ? project : ""}
          onClose={() => setDrawerId(null)}
          onReload={load}
          onCreated={() => {
            setDrawerId(null);
            showNotice("success", "Task created");
            load();
          }}
          onRequestDelete={(t) => setDeleteTarget(t)}
          onAskOrbit={() => navigate("/chat")}
          triggerRef={triggerRef}
        />
      )}

      {deleteTarget && (
        <Modal title="Delete task?" onClose={() => setDeleteTarget(null)}>
          <p className="confirm-text">"{deleteTarget.title}"</p>
          <p className="confirm-hint">This cannot be undone.</p>
          <div className="modal-footer">
            <OrbitButton variant="ghost" onClick={() => setDeleteTarget(null)}>Cancel</OrbitButton>
            <OrbitButton variant="danger" onClick={confirmDelete}>Delete</OrbitButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
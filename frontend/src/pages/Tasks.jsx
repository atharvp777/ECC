import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getTasks, createTask, updateTask, deleteTask, getProjects, getGithubRepos, pushTaskToGithub } from "../api";
import { Plus, Trash2, Check, CheckSquare, GitBranch } from "lucide-react";
import Modal from "../components/Modal";

const PRIORITIES = ["critical", "high", "medium", "low"];
const STATUSES   = ["todo", "in_progress", "blocked", "done"];

function TaskForm({ projects, onSave, onClose, defaultProjectId }) {
  const [form, setForm] = useState({
    title: "", description: "", priority: "medium", status: "todo",
    deadline: "", estimated_minutes: "", project_id: defaultProjectId || "",
  });
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.title.trim()) return;
    await createTask({
      ...form,
      deadline: form.deadline ? new Date(form.deadline).toISOString() : null,
      estimated_minutes: form.estimated_minutes ? parseInt(form.estimated_minutes) : null,
      project_id: form.project_id || null,
    });
    onSave();
  };

  return (
    <>
      <div className="form-group">
        <label className="form-label">Task Title *</label>
        <input className="form-input" value={form.title} onChange={e => set("title", e.target.value)} placeholder="e.g. Finish HV wiring diagram" autoFocus />
      </div>
      <div className="form-group">
        <label className="form-label">Description</label>
        <textarea className="form-textarea" value={form.description} onChange={e => set("description", e.target.value)} style={{ minHeight: 60 }} />
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Priority</label>
          <select className="form-select" value={form.priority} onChange={e => set("priority", e.target.value)}>
            {PRIORITIES.map(p => <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label">Status</label>
          <select className="form-select" value={form.status} onChange={e => set("status", e.target.value)}>
            {STATUSES.map(s => <option key={s} value={s}>{s.replace("_"," ")}</option>)}
          </select>
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Deadline</label>
          <input type="datetime-local" className="form-input" value={form.deadline} onChange={e => set("deadline", e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label">Est. Time (mins)</label>
          <input type="number" className="form-input" value={form.estimated_minutes} onChange={e => set("estimated_minutes", e.target.value)} placeholder="90" />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Project</label>
        <select className="form-select" value={form.project_id} onChange={e => set("project_id", e.target.value)}>
          <option value="">— No Project —</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={submit}>Add Task</button>
      </div>
    </>
  );
}

export default function Tasks() {
  const [tasks, setTasks]       = useState([]);
  const [projects, setProjects] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState({ status: "", priority: "" });
  const [searchParams]          = useSearchParams();
  const projectFilter           = searchParams.get("project");
  const [ghModal, setGhModal]   = useState(null);   // task being pushed to GH
  const [ghRepos, setGhRepos]   = useState([]);
  const [ghRepo, setGhRepo]     = useState("");

  const load = async () => {
    try {
      const params = {};
      if (projectFilter) params.project_id = projectFilter;
      if (filter.status)   params.status   = filter.status;
      if (filter.priority) params.priority = filter.priority;
      const [t, p] = await Promise.all([getTasks(params), getProjects()]);
      setTasks(t); setProjects(p);
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter, projectFilter]);

  const toggleDone = async (task) => {
    await updateTask(task.id, { status: task.status === "done" ? "todo" : "done" });
    load();
  };

  const openGhModal = async (task) => {
    setGhModal(task);
    try {
      const r = await getGithubRepos();
      setGhRepos(r.repos || []);
      if (r.repos?.length) setGhRepo(r.repos[0].full_name);
    } catch { setGhRepos([]); }
  };

  const pushToGithub = async () => {
    if (!ghRepo || !ghModal) return;
    try {
      const issue = await pushTaskToGithub({
        repo: ghRepo, title: ghModal.title,
        body: `${ghModal.description || ""}\n\n---\n*Pushed from Engineering Command Center*\nPriority: ${ghModal.priority}`,
        labels: ["ecc-task", ghModal.priority],
      });
      alert(`✓ Created GitHub issue #${issue.number}: ${issue.url}`);
      setGhModal(null);
    } catch (e) {
      alert("Failed: " + (e.response?.data?.detail || e.message));
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this task?")) return;
    await deleteTask(id); load();
  };

  const projectName = (id) => projects.find(p => p.id === id)?.name;

  if (loading) return <div className="spinner" />;

  return (
    <div className="page">
      <div className="section-header">
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>
          Tasks {projectFilter && projects.find(p => p.id == projectFilter) && `· ${projects.find(p => p.id == projectFilter).name}`}
        </h2>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          <Plus size={14} /> New Task
        </button>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <select className="form-select" style={{ width: "auto" }} value={filter.status} onChange={e => setFilter(f => ({ ...f, status: e.target.value }))}>
          <option value="">All Statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </select>
        <select className="form-select" style={{ width: "auto" }} value={filter.priority} onChange={e => setFilter(f => ({ ...f, priority: e.target.value }))}>
          <option value="">All Priorities</option>
          {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>

      {tasks.length === 0
        ? (
          <div className="empty">
            <CheckSquare size={40} style={{ margin: "0 auto 12px", display: "block", opacity: .3 }} />
            <p>No tasks found. Add your first one!</p>
          </div>
        )
        : (
          <div className="task-list">
            {tasks.map(task => {
              const overdue = task.deadline && new Date(task.deadline) < new Date() && task.status !== "done";
              return (
                <div className="task-item" key={task.id}>
                  <button className={`task-check ${task.status === "done" ? "done" : ""}`} onClick={() => toggleDone(task)}>
                    {task.status === "done" && <Check size={10} />}
                  </button>
                  <div className="task-body">
                    <div className={`task-title ${task.status === "done" ? "done" : ""}`}>{task.title}</div>
                    <div className="task-meta">
                      <span className={`badge badge-${task.priority}`}>{task.priority}</span>
                      <span className={`badge badge-${task.status}`}>{task.status.replace("_", " ")}</span>
                      {task.deadline && <span className={overdue ? "overdue" : ""}>{overdue ? "⚠ " : ""}{new Date(task.deadline).toLocaleDateString()}</span>}
                      {task.project_id && <span>📁 {projectName(task.project_id)}</span>}
                      {task.estimated_minutes && <span>⏱ {task.estimated_minutes}m</span>}
                    </div>
                  </div>
                  <div className="task-actions">
                    <button className="btn btn-ghost btn-sm" title="Push to GitHub" onClick={() => openGhModal(task)}><GitBranch size={12} /></button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(task.id)}><Trash2 size={12} /></button>
                  </div>
                </div>
              );
            })}
          </div>
        )
      }

      {showModal && (
        <Modal title="New Task" onClose={() => setShowModal(false)}>
          <TaskForm
            projects={projects}
            defaultProjectId={projectFilter}
            onSave={() => { setShowModal(false); load(); }}
            onClose={() => setShowModal(false)}
          />
        </Modal>
      )}

      {ghModal && (
        <Modal title="Push to GitHub" onClose={() => setGhModal(null)}>
          <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 16 }}>
            Create a GitHub issue from: <strong style={{ color: "var(--text)" }}>{ghModal.title}</strong>
          </p>
          {ghRepos.length === 0
            ? <p style={{ color: "var(--danger)", fontSize: 13 }}>No repos found. Check GITHUB_PAT in your .env</p>
            : (
              <div className="form-group">
                <label className="form-label">Target Repository</label>
                <select className="form-select" value={ghRepo} onChange={e => setGhRepo(e.target.value)}>
                  {ghRepos.map(r => <option key={r.full_name} value={r.full_name}>{r.full_name}</option>)}
                </select>
              </div>
            )
          }
          <div className="modal-footer">
            <button className="btn btn-ghost" onClick={() => setGhModal(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={pushToGithub} disabled={!ghRepo}>
              <GitBranch size={14} /> Create Issue
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}


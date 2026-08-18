import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getProject, getTasks, createTask, updateTask, deleteTask,
  getDocuments, uploadDocument, deleteDocument, getDocumentDownloadUrl,
} from "../api";
import { Plus, Trash2, Check, Upload, Download, File, ArrowLeft } from "lucide-react";
import Modal from "../components/Modal";

export const CATEGORY_LABELS = {
  personal: "Personal",
  baja: "Baja",
  jobprep: "JobPrep",
  college: "College",
  studyabroad: "Study Abroad",
};

const PRIORITIES = ["critical", "high", "medium", "low"];
const STATUSES = ["todo", "in_progress", "blocked", "done"];

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [docs, setDocs] = useState([]);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef();

  const loadAll = async () => {
    try {
      const p = await getProject(id);
      setProject(p);
      const [t, d] = await Promise.all([getTasks({ project_id: id }), getDocuments({ project_id: id })]);
      setTasks(t); setDocs(d);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
    finally { setLoading(false); }
  };

  useEffect(() => { loadAll(); }, [id]);

  const toggleDone = async (task) => {
    try {
      await updateTask(task.id, { status: task.status === "done" ? "todo" : "done" });
      loadAll();
    } catch (err) {
      alert("Failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const handleDeleteTask = async (taskId) => {
    if (!confirm("Delete this task?")) return;
    try {
      await deleteTask(taskId); loadAll();
    } catch (err) {
      alert("Failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("project_id", id);
      await uploadDocument(fd);
      loadAll();
    } catch (err) {
      alert("Upload failed: " + (err.response?.data?.detail || err.message));
    } finally { setUploading(false); e.target.value = ""; }
  };

  const handleDeleteDoc = async (docId) => {
    if (!confirm("Delete this document?")) return;
    try {
      await deleteDocument(docId); loadAll();
    } catch (err) {
      alert("Failed: " + (err.response?.data?.detail || err.message));
    }
  };

  if (loading) return <div className="spinner" />;
  if (loadError) return <div className="empty"><p>⚠ Couldn't load this project. Check the backend connection.</p></div>;
  if (!project) return <div className="empty"><p>Project not found.</p></div>;

  const pct = project.task_count ? Math.round((project.done_tasks || 0) / project.task_count * 100) : 0;

  return (
    <div className="page">
      <button className="btn btn-ghost btn-sm" onClick={() => navigate("/projects")} style={{ marginBottom: 14 }}>
        <ArrowLeft size={12} /> All Projects
      </button>

      {/* Header */}
      <div className="card" style={{ marginBottom: 16, overflow: "hidden" }}>
        <div className="color-bar" style={{ background: project.color }} />
        <div style={{ padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <h2 style={{ fontSize: 18, fontWeight: 700 }}>{project.name}</h2>
              <div className="cat" style={{ marginTop: 4 }}>
                {CATEGORY_LABELS[project.category] || project.category} · {project.status}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span className={`badge badge-${project.category}`}>{CATEGORY_LABELS[project.category] || project.category}</span>
            </div>
          </div>
          {project.description && (
            <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 10, lineHeight: 1.5 }}>{project.description}</p>
          )}
          {project.deadline && (
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
              Deadline: {new Date(project.deadline).toLocaleDateString()}
            </p>
          )}
          <div className="progress-row" style={{ marginTop: 14 }}>
            <div className="progress-bar" style={{ flex: 1 }}>
              <div className="progress-fill" style={{ width: `${pct}%`, background: project.color }} />
            </div>
            <span style={{ fontSize: 11, color: "var(--muted)", flexShrink: 0 }}>
              {project.done_tasks || 0}/{project.task_count || 0} tasks done
              {project.overdue_tasks ? ` · ${project.overdue_tasks} overdue` : ""}
            </span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="tab-row" style={{ display: "flex", gap: 4, marginBottom: 16, borderBottom: "1px solid var(--border)" }}>
        {[
          ["overview", "Overview"],
          ["tasks", "Tasks"],
          ["documents", "Documents"],
        ].map(([key, label]) => (
          <button
            key={key}
            className={`btn btn-sm ${tab === key ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setTab(key)}
            style={{ borderRadius: "8px 8px 0 0" }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Overview */}
      {tab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
          <div className="card card-sm">
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Tasks</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{project.task_count || 0}</div>
          </div>
          <div className="card card-sm">
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Done</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{project.done_tasks || 0}</div>
          </div>
          <div className="card card-sm">
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Overdue</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4, color: "var(--danger)" }}>{project.overdue_tasks || 0}</div>
          </div>
          <div className="card card-sm">
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Documents</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{docs.length}</div>
          </div>
        </div>
      )}

      {/* Tasks */}
      {tab === "tasks" && (
        <div>
          <div className="section-header" style={{ marginBottom: 12 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Tasks</span>
            <button className="btn btn-primary btn-sm" onClick={() => setShowTaskModal(true)}>
              <Plus size={12} /> New Task
            </button>
          </div>
          {tasks.length === 0 ? (
            <div className="empty" style={{ padding: 30 }}>
              <p style={{ fontSize: 13 }}>No tasks in this project yet.</p>
            </div>
          ) : (
            <div className="task-list">
              {tasks.map(task => (
                <div className="task-item" key={task.id}>
                  <button className={`task-check ${task.status === "done" ? "done" : ""}`} onClick={() => toggleDone(task)}>
                    {task.status === "done" && <Check size={10} />}
                  </button>
                  <div className="task-body">
                    <div className={`task-title ${task.status === "done" ? "done" : ""}`}>{task.title}</div>
                    <div className="task-meta">
                      <span className={`badge badge-${task.priority}`}>{task.priority}</span>
                      <span className={`badge badge-${task.status}`}>{task.status.replace("_", " ")}</span>
                      {task.task_type && task.task_type !== "work" && (
                        <span className="tag">{task.task_type}</span>
                      )}
                      {task.deadline && <span>Due {new Date(task.deadline).toLocaleDateString()}</span>}
                      {task.google_calendar_event_id && !task.calendar_sync_error && (
                        <span title="Linked to Google Calendar">📅 On calendar</span>
                      )}
                      {task.calendar_sync_error && (
                        <span className="badge badge-danger">⚠ Calendar sync failed</span>
                      )}
                    </div>
                  </div>
                  <div className="task-actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDeleteTask(task.id)}><Trash2 size={12} /></button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Documents */}
      {tab === "documents" && (
        <div>
          <div className="section-header" style={{ marginBottom: 12 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Documents</span>
            <input ref={inputRef} type="file" style={{ display: "none" }} onChange={handleUpload}
              accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp" />
            <button className="btn btn-primary btn-sm" onClick={() => inputRef.current.click()} disabled={uploading}>
              <Upload size={12} /> {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
          {docs.length === 0 ? (
            <div className="empty" style={{ padding: 30 }}>
              <File size={30} style={{ margin: "0 auto 10px", display: "block", opacity: .3 }} />
              <p style={{ fontSize: 13 }}>No documents uploaded to this project.</p>
              <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>PDFs, text, Markdown, DOCX, PNG, JPG.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {docs.map(doc => (
                <div key={doc.id} className="card card-sm" style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <File size={20} color="var(--accent)" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {doc.title || doc.original_filename}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                      {fmtSize(doc.file_size_bytes)} · {new Date(doc.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <a className="btn btn-ghost btn-sm" title="Download" href={getDocumentDownloadUrl(doc.id)}><Download size={12} /></a>
                  <button className="btn btn-ghost btn-sm" onClick={() => handleDeleteDoc(doc.id)}><Trash2 size={12} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showTaskModal && (
        <Modal title="New Task" onClose={() => setShowTaskModal(false)}>
          <TaskForm projectId={id} onSave={() => { setShowTaskModal(false); loadAll(); }} onClose={() => setShowTaskModal(false)} />
        </Modal>
      )}
    </div>
  );
}

function TaskForm({ projectId, onSave, onClose }) {
  const [form, setForm] = useState({
    title: "", description: "", priority: "medium", status: "todo", deadline: "",
  });
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.title.trim()) return;
    await createTask({
      ...form,
      deadline: form.deadline ? new Date(form.deadline).toISOString() : null,
      project_id: projectId ? parseInt(projectId) : null,
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
            {STATUSES.map(s => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Deadline</label>
        <input type="datetime-local" className="form-input" value={form.deadline} onChange={e => set("deadline", e.target.value)} />
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={submit}>Add Task</button>
      </div>
    </>
  );
}
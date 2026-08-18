import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getTasks, createTask, updateTask, deleteTask, getProjects, linkTaskToCalendar, unlinkTaskFromCalendar } from "../api";
import { Plus, Trash2, Check, CheckSquare, Calendar, CalendarPlus, CalendarX, RefreshCw } from "lucide-react";
import Modal from "../components/Modal";

const PRIORITIES = ["critical", "high", "medium", "low"];
const STATUSES   = ["todo", "in_progress", "blocked", "done"];

function TaskForm({ projects, onSave, onClose, defaultProjectId }) {
  const [form, setForm] = useState({
    title: "", description: "", priority: "medium", status: "todo",
    deadline: "", estimated_minutes: "", project_id: defaultProjectId || "",
    schedule_date: "", schedule_time: "", duration_minutes: "",
  });
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.title.trim()) return;
    const payload = {
      ...form,
      deadline: form.deadline ? new Date(form.deadline).toISOString() : null,
      estimated_minutes: form.estimated_minutes ? parseInt(form.estimated_minutes) : null,
      project_id: form.project_id || null,
      schedule_on_calendar: false,
    };
    delete payload.schedule_date; delete payload.schedule_time;
    // Schedule = when the user intends to WORK (goes to Google Calendar).
    // Deadline = when the task is DUE (no calendar event).
    if (form.schedule_date) {
      const when = form.schedule_time ? `${form.schedule_date}T${form.schedule_time}` : `${form.schedule_date}T09:00`;
      payload.scheduled_start = when;
      payload.schedule_on_calendar = true;
      payload.duration_minutes = form.duration_minutes ? parseInt(form.duration_minutes) : 60;
    }
    await createTask(payload);
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
        <label className="form-label">Schedule (Google Calendar)</label>
        <div className="form-row">
          <div className="form-group">
            <input type="date" className="form-input" value={form.schedule_date} onChange={e => set("schedule_date", e.target.value)} title="Work date" />
          </div>
          <div className="form-group">
            <input type="time" className="form-input" value={form.schedule_time} onChange={e => set("schedule_time", e.target.value)} title="Start time" />
          </div>
          <div className="form-group">
            <input type="number" min="1" className="form-input" value={form.duration_minutes} onChange={e => set("duration_minutes", e.target.value)} placeholder="60 min" title="Duration" />
          </div>
        </div>
        <p className="form-hint" style={{ fontSize: 12, color: "var(--muted)" }}>Set a work date/time to also add this task to your Google Calendar.</p>
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
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter]     = useState({ status: "", priority: "" });
const [searchParams]          = useSearchParams();
  const projectFilter           = searchParams.get("project");

  const load = async () => {
    try {
      const params = {};
      if (projectFilter) params.project_id = projectFilter;
      if (filter.status)   params.status   = filter.status;
      if (filter.priority) params.priority = filter.priority;
      const [t, p] = await Promise.all([getTasks(params), getProjects()]);
      setTasks(t); setProjects(p);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter, projectFilter]);

  const toggleDone = async (task) => {
    try {
      await updateTask(task.id, { status: task.status === "done" ? "todo" : "done" });
      load();
    } catch (e) {
      alert("Failed: " + (e.response?.data?.detail || e.message));
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this task?")) return;
    try {
      await deleteTask(id); load();
    } catch (e) {
      alert("Failed: " + (e.response?.data?.detail || e.message));
    }
  };

  // Task ↔ Google Calendar
  const [calModal, setCalModal] = useState(null); // task being added to calendar
  const [calForm, setCalForm]   = useState({ date: "", time: "", duration: "60" });

  const openCalModal = (task) => {
    setCalForm({ date: "", time: "", duration: "60" });
    setCalModal(task);
  };

  const handleAddToCalendar = async () => {
    if (!calModal || !calForm.date) return;
    try {
      await linkTaskToCalendar(calModal.id, {
        when: calForm.date,
        start_time: calForm.time || null,
        duration_minutes: parseInt(calForm.duration) || 60,
      });
      setCalModal(null);
      load();
    } catch (e) {
      alert("Failed: " + (e.response?.data?.detail || e.message));
    }
  };

  const handleRemoveFromCalendar = async (task) => {
    if (!confirm(`Remove "${task.title}" from your Google Calendar? (The task is kept.)`)) return;
    try {
      await unlinkTaskFromCalendar(task.id);
      load();
    } catch (e) {
      alert("Failed: " + (e.response?.data?.detail || e.message));
    }
  };

  const handleRetrySync = async (task) => {
    try {
      await linkTaskToCalendar(task.id, {
        scheduled_start: task.scheduled_start || null,
        scheduled_end: task.scheduled_end || null,
        duration_minutes: 60,
      });
      load();
    } catch (e) {
      alert("Failed: " + (e.response?.data?.detail || e.message));
    }
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

{loadError && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--warning)", textAlign: "center" }}>
          <p style={{ color: "var(--warning)", fontSize: 13 }}>
            ⚠ Couldn't load tasks. Check the backend connection.
          </p>
        </div>
      )}

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
                  <button className={`task-check ${task.status === "done" ? "done" : ""}`} onClick={() => toggleDone(task)} aria-label={task.status === "done" ? `Reopen ${task.title}` : `Complete ${task.title}`}>
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
                      {task.google_calendar_event_id && !task.calendar_sync_error && (
                        <span title="Linked to Google Calendar">📅 {task.scheduled_start ? new Date(task.scheduled_start).toLocaleDateString() : "On calendar"}</span>
                      )}
                      {task.calendar_sync_error && (
                        <span className="badge badge-danger" title={task.calendar_sync_error}>⚠ Calendar sync failed</span>
                      )}
                    </div>
                  </div>
                  <div className="task-actions">
                    {task.calendar_sync_error && (
                      <button className="btn btn-ghost btn-sm" title="Retry calendar sync" onClick={() => handleRetrySync(task)}><RefreshCw size={12} /></button>
                    )}
                    {task.google_calendar_event_id
                      ? (
                        <button className="btn btn-ghost btn-sm" title="Remove from Google Calendar" onClick={() => handleRemoveFromCalendar(task)}><CalendarX size={12} /></button>
                      )
                      : (
                        <button className="btn btn-ghost btn-sm" title="Add to Google Calendar" onClick={() => openCalModal(task)}><CalendarPlus size={12} /></button>
                      )}
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(task.id)} aria-label={`Delete ${task.title}`}><Trash2 size={12} /></button>
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

      {calModal && (
        <Modal title="Add to Google Calendar" onClose={() => setCalModal(null)}>
          <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 16 }}>
            Add <strong style={{ color: "var(--text)" }}>{calModal.title}</strong> as calendar work time:
          </p>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Date *</label>
              <input type="date" className="form-input" value={calForm.date} onChange={e => setCalForm(f => ({ ...f, date: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label">Start Time</label>
              <input type="time" className="form-input" value={calForm.time} onChange={e => setCalForm(f => ({ ...f, time: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label">Duration (min)</label>
              <input type="number" min="1" className="form-input" value={calForm.duration} onChange={e => setCalForm(f => ({ ...f, duration: e.target.value }))} />
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-ghost" onClick={() => setCalModal(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleAddToCalendar} disabled={!calForm.date}>
              <Calendar size={14} /> Add to Calendar
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}


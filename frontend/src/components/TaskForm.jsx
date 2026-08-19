import { useState } from "react";
import { ChevronDown } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";

export const PRIORITIES = ["critical", "high", "medium", "low"];
export const STATUSES = ["todo", "in_progress", "blocked", "done"];
export const TASK_TYPES = ["work", "reminder", "meeting"];
export const STATUS_LABELS = { todo: "Todo", in_progress: "In progress", blocked: "Blocked", done: "Done" };
export const TYPE_LABELS = { work: "Work", reminder: "Reminder", meeting: "Meeting" };

const RECURRENCES = [
  ["never", "Never"],
  ["daily", "Daily"],
  ["weekly", "Weekly"],
];

function toLocalInput(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function emptyForm(defaultProjectId) {
  return {
    title: "",
    description: "",
    priority: "medium",
    status: "todo",
    task_type: "work",
    deadline: "",
    estimated_minutes: "",
    project_id: defaultProjectId || "",
    schedule_date: "",
    schedule_time: "",
    duration_minutes: "",
    recurrence: "never",
  };
}

function toForm(task) {
  return {
    title: task.title || "",
    description: task.description || "",
    priority: task.priority || "medium",
    status: task.status || "todo",
    task_type: task.task_type || "work",
    deadline: task.deadline ? toLocalInput(task.deadline) : "",
    estimated_minutes: task.estimated_minutes != null ? String(task.estimated_minutes) : "",
    project_id: task.project_id != null ? String(task.project_id) : "",
    schedule_date: "",
    schedule_time: "",
    duration_minutes: "",
    recurrence: task.recurrence_rule || "never",
  };
}

/**
 * Build the mutation payload. The backend treats null estimated_minutes as a
 * no-op, so an untouched/cleared estimate is simply omitted. Clearing a
 * deadline is a real clear, so explicit null is sent for it.
 */
function buildPayload(form, editing) {
  const payload = {
    title: form.title.trim(),
    description: form.description || null,
    priority: form.priority,
    status: form.status,
    task_type: form.task_type,
    project_id: form.project_id ? Number(form.project_id) : null,
    deadline: form.deadline ? new Date(form.deadline).toISOString() : null,
  };
  if (form.estimated_minutes) {
    payload.estimated_minutes = parseInt(form.estimated_minutes, 10);
  }
  if (form.recurrence && form.recurrence !== "never") {
    payload.is_recurring = true;
    payload.recurrence_rule = form.recurrence;
  } else if (editing) {
    payload.is_recurring = false;
    payload.recurrence_rule = null;
  }
  if (form.schedule_date) {
    const when = form.schedule_time ? `${form.schedule_date}T${form.schedule_time}` : `${form.schedule_date}T09:00`;
    payload.scheduled_start = when;
    payload.schedule_on_calendar = true;
    payload.duration_minutes = form.duration_minutes ? parseInt(form.duration_minutes, 10) : 60;
  }
  return payload;
}

/**
 * Compact create/edit form used inside the TaskDrawer. `onSave(payload)` is
 * responsible for the API call (createTask/updateTask) and should resolve on
 * success; this form shows its own saving state but no inline errors.
 */
export default function TaskForm({
  projects,
  initial,
  defaultProjectId,
  submitLabel = "Save",
  showSchedule = false,
  onSave,
  onCancel,
}) {
  const editing = Boolean(initial);
  const [form, setForm] = useState(() => (initial ? toForm(initial) : emptyForm(defaultProjectId)));
  const [advanced, setAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.title.trim() || saving) return;
    setSaving(true);
    try {
      await onSave(buildPayload(form, editing));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="task-form">
      <div className="form-group">
        <label className="form-label" htmlFor="tf-title">Task Title *</label>
        <input
          id="tf-title"
          className="form-input"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="e.g. Finish HV wiring diagram"
          autoFocus
        />
      </div>

      <div className="form-row">
        <div className="form-group">
          <label className="form-label" htmlFor="tf-project">Project</label>
          <select id="tf-project" className="form-select" value={form.project_id} onChange={(e) => set("project_id", e.target.value)}>
            <option value="">No project</option>
            {projects.map((p) => (
              <option key={p.id} value={String(p.id)}>{p.name}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="tf-type">Type</label>
          <select id="tf-type" className="form-select" value={form.task_type} onChange={(e) => set("task_type", e.target.value)}>
            {TASK_TYPES.map((t) => (
              <option key={t} value={t}>{TYPE_LABELS[t]}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label className="form-label" htmlFor="tf-priority">Priority</label>
          <select id="tf-priority" className="form-select" value={form.priority} onChange={(e) => set("priority", e.target.value)}>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>{p.toUpperCase()}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="tf-status">Status</label>
          <select id="tf-status" className="form-select" value={form.status} onChange={(e) => set("status", e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label className="form-label" htmlFor="tf-deadline">Deadline</label>
          <input id="tf-deadline" type="datetime-local" className="form-input" value={form.deadline} onChange={(e) => set("deadline", e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="tf-estimate">Estimate (minutes)</label>
          <input id="tf-estimate" type="number" min="1" className="form-input" value={form.estimated_minutes} onChange={(e) => set("estimated_minutes", e.target.value)} placeholder="45" />
        </div>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="tf-desc">Description</label>
        <textarea id="tf-desc" className="form-textarea" value={form.description} onChange={(e) => set("description", e.target.value)} style={{ minHeight: 70 }} />
      </div>

      <button type="button" className="task-form__advanced" aria-expanded={advanced} onClick={() => setAdvanced((a) => !a)}>
        Advanced
        <ChevronDown size={14} aria-hidden="true" />
      </button>

      {advanced && (
        <div className="task-form__advanced-body">
          {showSchedule && (
            <div className="form-group">
              <label className="form-label">Schedule (Google Calendar)</label>
              <div className="task-form__schedule-row">
                <input type="date" className="form-input" value={form.schedule_date} onChange={(e) => set("schedule_date", e.target.value)} title="Work date" aria-label="Schedule work date" />
                <input type="time" className="form-input" value={form.schedule_time} onChange={(e) => set("schedule_time", e.target.value)} title="Start time" aria-label="Schedule start time" />
                <input type="number" min="1" className="form-input" value={form.duration_minutes} onChange={(e) => set("duration_minutes", e.target.value)} placeholder="60 min" title="Duration" aria-label="Schedule duration (minutes)" />
              </div>
              <p className="form-hint task-form__hint">Set a work date/time to also add this task to your Google Calendar.</p>
            </div>
          )}
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="tf-recurrence">Repeats</label>
            <select id="tf-recurrence" className="form-select" value={form.recurrence} onChange={(e) => set("recurrence", e.target.value)}>
              {RECURRENCES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      <div className="modal-footer">
        <OrbitButton variant="ghost" onClick={onCancel}>Cancel</OrbitButton>
        <OrbitButton variant="primary" onClick={submit} loading={saving} disabled={!form.title.trim()}>{submitLabel}</OrbitButton>
      </div>
    </div>
  );
}
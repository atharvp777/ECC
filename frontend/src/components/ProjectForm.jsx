import { useState } from "react";
import OrbitButton from "./ui/OrbitButton";
import {
  CATEGORIES,
  PROJECT_STATUSES,
  PROJECT_COLORS,
} from "../utils/projects";

function emptyForm() {
  return {
    name: "",
    description: "",
    category: "personal",
    status: "active",
    deadline: "",
    color: PROJECT_COLORS[0],
  };
}

function toLocalDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function toForm(project) {
  return {
    name: project.name || "",
    description: project.description || "",
    category: project.category || "personal",
    status: project.status || "active",
    deadline: toLocalDate(project.deadline),
    color: project.color || PROJECT_COLORS[0],
  };
}

/**
 * Create/edit form used inside the ProjectDrawer. `onSave(payload)` is
 * responsible for the API call (createProject/updateProject) and resolves on
 * success; this form shows its own saving state.
 */
export default function ProjectForm({ initial, submitLabel = "Save", onSave, onCancel }) {
  const editing = Boolean(initial);
  const [form, setForm] = useState(() => (initial ? toForm(initial) : emptyForm()));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        name: form.name.trim(),
        description: form.description || null,
        category: form.category,
        status: form.status,
        deadline: form.deadline ? new Date(`${form.deadline}T12:00:00`).toISOString() : null,
        color: form.color,
      });
    } catch {
      setError(editing ? "Couldn't save the project." : "Couldn't create the project.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="task-form">
      {error && (
        <p className="task-drawer__error" role="alert">{error}</p>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor="pj-name">Project Name *</label>
        <input
          id="pj-name"
          className="form-input"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="e.g. HV Wiring System"
          autoFocus
        />
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="pj-desc">Description</label>
        <textarea
          id="pj-desc"
          className="form-textarea"
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          placeholder="What is this project about?"
          style={{ minHeight: 70 }}
        />
      </div>

      <div className="form-row">
        <div className="form-group">
          <label className="form-label" htmlFor="pj-category">Category</label>
          <select id="pj-category" className="form-select" value={form.category} onChange={(e) => set("category", e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="pj-status">Status</label>
          <select id="pj-status" className="form-select" value={form.status} onChange={(e) => set("status", e.target.value)}>
            {PROJECT_STATUSES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label className="form-label" htmlFor="pj-deadline">Deadline</label>
          <input id="pj-deadline" type="date" className="form-input" value={form.deadline} onChange={(e) => set("deadline", e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label">Color</label>
          <div className="project-form__colors" role="group" aria-label="Project color">
            {PROJECT_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className={`project-form__swatch${form.color === c ? " is-selected" : ""}`}
                style={{ background: c }}
                onClick={() => set("color", c)}
                aria-label={`Project color ${c}`}
                aria-pressed={form.color === c}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="modal-footer">
        <OrbitButton variant="ghost" onClick={onCancel}>Cancel</OrbitButton>
        <OrbitButton variant="primary" onClick={submit} loading={saving} disabled={!form.name.trim()}>
          {submitLabel}
        </OrbitButton>
      </div>
    </div>
  );
}
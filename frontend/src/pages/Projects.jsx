import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getProjects, createProject, deleteProject } from "../api/client";
import { Plus, Trash2, FolderOpen } from "lucide-react";
import Modal from "../components/Modal";

const CATEGORIES = ["baja", "agrovault", "college", "personal", "internship"];
const COLORS = ["#4f7cff", "#7c3aed", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4"];

function ProjectForm({ onSave, onClose }) {
  const [form, setForm] = useState({ name: "", description: "", category: "personal", color: "#4f7cff", deadline: "" });
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.name.trim()) return;
    await createProject({ ...form, deadline: form.deadline || null });
    onSave();
  };

  return (
    <>
      <div className="form-group">
        <label className="form-label">Project Name *</label>
        <input className="form-input" value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. HV Wiring System" autoFocus />
      </div>
      <div className="form-group">
        <label className="form-label">Description</label>
        <textarea className="form-textarea" value={form.description} onChange={e => set("description", e.target.value)} placeholder="What is this project about?" style={{ minHeight: 70 }} />
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Category</label>
          <select className="form-select" value={form.category} onChange={e => set("category", e.target.value)}>
            {CATEGORIES.map(c => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label">Deadline</label>
          <input type="date" className="form-input" value={form.deadline} onChange={e => set("deadline", e.target.value)} />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Color</label>
        <div style={{ display: "flex", gap: 8 }}>
          {COLORS.map(c => (
            <button key={c} onClick={() => set("color", c)} style={{
              width: 28, height: 28, borderRadius: "50%", background: c, border: "none", cursor: "pointer",
              outline: form.color === c ? `3px solid ${c}` : "3px solid transparent", outlineOffset: 2,
            }} />
          ))}
        </div>
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={submit}>Create Project</button>
      </div>
    </>
  );
}

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = async () => {
    try { setProjects(await getProjects()); } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (!confirm("Delete this project and all its tasks?")) return;
    await deleteProject(id);
    load();
  };

  if (loading) return <div className="spinner" />;

  return (
    <div className="page">
      <div className="section-header">
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>Projects</h2>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          <Plus size={14} /> New Project
        </button>
      </div>

      {projects.length === 0
        ? (
          <div className="empty">
            <FolderOpen size={40} style={{ margin: "0 auto 12px", display: "block", opacity: .3 }} />
            <p>No projects yet. Create your first one!</p>
          </div>
        )
        : (
          <div className="project-grid">
            {projects.map(p => {
              const pct = p.task_count ? Math.round((p.done_tasks || 0) / p.task_count * 100) : 0;
              return (
                <div className="project-card" key={p.id} onClick={() => navigate(`/tasks?project=${p.id}`)}>
                  <div className="color-bar" style={{ background: p.color }} />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <h4>{p.name}</h4>
                      <div className="cat">{p.category} · {p.status}</div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={e => handleDelete(e, p.id)}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                  {p.description && <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6, lineHeight: 1.4 }}>{p.description}</p>}
                  <div className="progress-row" style={{ marginTop: 14 }}>
                    <div className="progress-bar">
                      <div className="progress-fill" style={{ width: `${pct}%`, background: p.color }} />
                    </div>
                    <span style={{ fontSize: 11, color: "var(--muted)", flexShrink: 0 }}>{p.task_count} tasks</span>
                  </div>
                </div>
              );
            })}
          </div>
        )
      }

      {showModal && (
        <Modal title="New Project" onClose={() => setShowModal(false)}>
          <ProjectForm onSave={() => { setShowModal(false); load(); }} onClose={() => setShowModal(false)} />
        </Modal>
      )}
    </div>
  );
}

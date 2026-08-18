import { useEffect, useState } from "react";
import { getNotes, createNote, updateNote, deleteNote, getProjects } from "../api";
import { Plus, Trash2, FileText } from "lucide-react";

export default function Notes() {
  const [notes, setNotes]       = useState([]);
  const [projects, setProjects] = useState([]);
const [active, setActive]     = useState(null);
  const [saving, setSaving]     = useState(false);
  const [timer, setTimer]       = useState(null);
  const [loadError, setLoadError] = useState(false);

  const load = async () => {
    try {
      const [n, p] = await Promise.all([getNotes(), getProjects()]);
      setNotes(n); setProjects(p);
      if (n.length && !active) setActive(n[0]);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  };

  useEffect(() => { load(); }, []);

  const newNote = async () => {
    try {
      const note = await createNote({ title: "Untitled Note", content: "" });
      await load();
      setActive(note);
    } catch (err) {
      alert("Failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this note?")) return;
    try {
      await deleteNote(id);
      setActive(null);
      load();
    } catch (err) {
      alert("Failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const autoSave = (field, value) => {
    setActive(a => ({ ...a, [field]: value }));
    if (timer) clearTimeout(timer);
    setTimer(setTimeout(async () => {
      setSaving(true);
      await updateNote(active.id, { [field]: value });
      setSaving(false);
      load();
    }, 800));
  };

  const projectName = (id) => projects.find(p => p.id === id)?.name;

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* Note list sidebar */}
      <div style={{ width: 240, borderRight: "1px solid var(--border)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "16px 12px 8px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border)" }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Notes</span>
          <button className="btn btn-ghost btn-sm" onClick={newNote}><Plus size={14} /></button>
        </div>
        <div style={{ overflowY: "auto", flex: 1 }}>
          {notes.map(note => (
            <div
              key={note.id}
              onClick={() => setActive(note)}
              style={{
                padding: "10px 14px", cursor: "pointer", borderBottom: "1px solid var(--border)",
                background: active?.id === note.id ? "var(--surface2)" : "transparent",
                borderLeft: active?.id === note.id ? "3px solid var(--accent)" : "3px solid transparent",
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{note.title}</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                {note.project_id ? projectName(note.project_id) : "Personal"} · {new Date(note.updated_at).toLocaleDateString()}
              </div>
            </div>
          ))}
{notes.length === 0 && (
            <div className="empty" style={{ padding: 24 }}>
              <FileText size={24} style={{ margin: "0 auto 8px", display: "block", opacity: .3 }} />
              <p style={{ fontSize: 12 }}>{loadError ? "Couldn't load notes — is the backend running?" : "No notes yet"}</p>
            </div>
          )}
        </div>
      </div>

      {/* Editor */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {active ? (
          <div style={{ flex: 1, padding: 24, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <select className="form-select" style={{ width: "auto", fontSize: 12, padding: "4px 8px" }}
                  value={active.project_id || ""}
                  onChange={e => autoSave("project_id", e.target.value || null)}>
                  <option value="">Personal</option>
                  {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                {saving && <span style={{ fontSize: 11, color: "var(--muted)" }}>Saving…</span>}
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(active.id)}><Trash2 size={12} /></button>
            </div>
            <input
              className="note-title-input"
              value={active.title}
              onChange={e => autoSave("title", e.target.value)}
              placeholder="Note title"
            />
            <div className="divider" />
            <textarea
              className="note-content-input"
              value={active.content}
              onChange={e => autoSave("content", e.target.value)}
              placeholder="Start writing… (supports plain text and Markdown)"
              style={{ flex: 1, overflow: "auto" }}
            />
          </div>
        ) : (
          <div className="empty" style={{ margin: "auto" }}>
            <FileText size={40} style={{ margin: "0 auto 12px", display: "block", opacity: .3 }} />
            <p>Select a note or create a new one</p>
            <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={newNote}><Plus size={14} /> New Note</button>
          </div>
        )}
      </div>
    </div>
  );
}


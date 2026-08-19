import { useState } from "react";
import { Plus, StickyNote, Pencil, Trash2, Check, X } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import OrbitEmptyState from "./ui/OrbitEmptyState";
import { formatShortDate } from "../utils/format";

function excerpt(note) {
  const text = (note.content || "").replace(/\s+/g, " ").trim();
  return text.length > 120 ? `${text.slice(0, 120)}…` : text;
}

/**
 * Scoped notes view for a project workspace. Supports the existing note
 * operations: create, edit (inline), delete. No invented functionality.
 */
export default function ProjectNotes({ notes, onCreate, onUpdate, onDelete }) {
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({ title: "", content: "" });
  const [saving, setSaving] = useState(false);

  const startEdit = (note) => {
    setEditingId(note.id);
    setDraft({ title: note.title || "", content: note.content || "" });
  };

  const addNote = async () => {
    const note = await onCreate();
    if (note) startEdit(note);
  };

  const save = async () => {
    if (!editingId || saving) return;
    setSaving(true);
    try {
      await onUpdate(editingId, { title: draft.title.trim() || "Untitled note", content: draft.content });
      setEditingId(null);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="project-notes">
      <div className="project-notes__toolbar">
        <OrbitButton variant="secondary" onClick={addNote}>
          <Plus size={14} aria-hidden="true" /> Add note
        </OrbitButton>
      </div>

      {notes.length === 0 ? (
        <OrbitEmptyState
          icon={StickyNote}
          title="No notes yet."
          description="Capture thoughts, decisions, and context specific to this project."
          action={
            <OrbitButton variant="secondary" onClick={addNote}>
              <Plus size={14} aria-hidden="true" /> Add note
            </OrbitButton>
          }
        />
      ) : (
        <div className="project-notes__list">
          {notes.map((note) => (
            <div key={note.id} className="project-notes__card">
              {editingId === note.id ? (
                <div className="project-notes__editor">
                  <input
                    className="form-input"
                    value={draft.title}
                    onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
                    placeholder="Note title"
                    aria-label="Note title"
                    autoFocus
                  />
                  <textarea
                    className="form-textarea"
                    value={draft.content}
                    onChange={(e) => setDraft((d) => ({ ...d, content: e.target.value }))}
                    placeholder="Start writing…"
                    aria-label="Note content"
                    style={{ minHeight: 120 }}
                  />
                  <div className="project-notes__editor-actions">
                    <OrbitButton size="sm" variant="primary" onClick={save} loading={saving}>
                      <Check size={12} aria-hidden="true" /> Save
                    </OrbitButton>
                    <OrbitButton size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                      <X size={12} aria-hidden="true" /> Cancel
                    </OrbitButton>
                  </div>
                </div>
              ) : (
                <>
                  <div className="project-notes__body">
                    <div className="project-notes__title">{note.title || "Untitled note"}</div>
                    {excerpt(note) && <div className="project-notes__excerpt">{excerpt(note)}</div>}
                    <div className="project-notes__date">
                      Updated {formatShortDate(note.updated_at)}
                    </div>
                  </div>
                  <div className="project-notes__actions">
                    <button
                      type="button"
                      className="task-action-btn"
                      title="Edit note"
                      aria-label={`Edit ${note.title || "Untitled note"}`}
                      onClick={() => startEdit(note)}
                    >
                      <Pencil size={13} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="task-action-btn task-action-btn--danger"
                      title="Delete note"
                      aria-label={`Delete ${note.title || "Untitled note"}`}
                      onClick={() => onDelete(note)}
                    >
                      <Trash2 size={13} aria-hidden="true" />
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
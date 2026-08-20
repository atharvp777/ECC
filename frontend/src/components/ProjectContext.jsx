import { useState } from "react";
import { Plus, Brain, Pencil, Trash2, Check, X } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import OrbitEmptyState from "./ui/OrbitEmptyState";
import { formatShortDate } from "../utils/format";

/**
 * Scoped durable-memory view for a project workspace. Mirrors the notes
 * interaction: create, inline edit, delete. Unlike notes, a context item is a
 * single concise fact (no title) that the project-scoped AI treats as DATA.
 */
export default function ProjectContext({ items, onCreate, onUpdate, onDelete }) {
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const startEdit = (item) => {
    setEditingId(item.id);
    setDraft(item.content || "");
  };

  const addItem = async () => {
    const item = await onCreate();
    if (item) startEdit(item);
  };

  const save = async () => {
    if (!editingId || saving) return;
    const content = draft.trim();
    if (!content) return;
    setSaving(true);
    try {
      await onUpdate(editingId, { content });
      setEditingId(null);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="project-context">
      <div className="project-context__toolbar">
        <p className="project-context__hint">
          Durable facts about this project that Orbit remembers. The project AI
          uses these as reference data when answering.
        </p>
        <OrbitButton variant="secondary" onClick={addItem}>
          <Plus size={14} aria-hidden="true" /> Add fact
        </OrbitButton>
      </div>

      {items.length === 0 ? (
        <OrbitEmptyState
          icon={Brain}
          title="No project context yet."
          description="Save a decision, constraint, or preference and Orbit will remember it for this project."
          action={
            <OrbitButton variant="secondary" onClick={addItem}>
              <Plus size={14} aria-hidden="true" /> Add fact
            </OrbitButton>
          }
        />
      ) : (
        <div className="project-context__list">
          {items.map((item) => (
            <div key={item.id} className="project-context__card">
              {editingId === item.id ? (
                <div className="project-context__editor">
                  <textarea
                    className="form-textarea"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="What should Orbit remember about this project?"
                    aria-label="Context fact"
                    autoFocus
                    style={{ minHeight: 72 }}
                  />
                  <div className="project-context__editor-actions">
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
                  <div className="project-context__body">
                    <div className="project-context__text">{item.content}</div>
                    {item.category && (
                      <span className="project-context__category">{item.category}</span>
                    )}
                    <div className="project-context__date">
                      Updated {formatShortDate(item.updated_at)}
                    </div>
                  </div>
                  <div className="project-context__actions">
                    <button
                      type="button"
                      className="task-action-btn"
                      title="Edit fact"
                      aria-label="Edit context fact"
                      onClick={() => startEdit(item)}
                    >
                      <Pencil size={13} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="task-action-btn task-action-btn--danger"
                      title="Delete fact"
                      aria-label="Delete context fact"
                      onClick={() => onDelete(item)}
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
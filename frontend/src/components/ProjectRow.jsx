import { Pencil, Trash2 } from "lucide-react";
import OrbitBadge from "./ui/OrbitBadge";
import {
  CATEGORY_LABELS,
  STATUS_LABELS,
  STATUS_BADGE,
  formatProjectDeadline,
  projectPercent,
} from "../utils/projects";

/**
 * Compact project row for the Projects index. Rows open the project workspace
 * (Enter works too); edit/delete are hover/focus actions.
 */
export default function ProjectRow({ project, onOpen, onEdit, onDelete }) {
  const total = project.task_count || 0;
  const done = project.done_tasks || 0;
  const pct = projectPercent(done, total);
  const deadline = formatProjectDeadline(project.deadline);
  const statusLabel = STATUS_LABELS[project.status] || project.status;
  const statusVariant = STATUS_BADGE[project.status] || "default";

  const open = (e) => {
    e.stopPropagation();
    onOpen(project);
  };

  return (
    <div
      className="project-row"
      role="button"
      tabIndex={0}
      onClick={() => onOpen(project)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          onOpen(project);
        }
      }}
    >
      <span className="project-row__dot" style={{ background: project.color }} aria-hidden="true" />

      <div className="project-row__main">
        <div className="project-row__title">{project.name}</div>
        {project.description && <div className="project-row__desc">{project.description}</div>}
        <div className="project-row__meta">
          <OrbitBadge variant={statusVariant}>{statusLabel}</OrbitBadge>
          <span className="project-row__meta-item">
            {CATEGORY_LABELS[project.category] || project.category}
          </span>
          {deadline && (
            <span className={`project-row__meta-item${deadline.startsWith("Overdue") ? " project-row__meta-item--overdue" : ""}`}>
              {deadline}
            </span>
          )}
        </div>
      </div>

      <div className="project-row__progress">
        <div className="project-row__progress-label">
          {total === 0 ? (
            <span className="project-row__no-tasks">No tasks yet</span>
          ) : (
            <span>{done} / {total} completed</span>
          )}
          {pct != null && <span className="project-row__percent">{pct}%</span>}
        </div>
        {total > 0 && (
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%`, background: project.color }} />
          </div>
        )}
      </div>

      <div className="project-row__actions">
        <button
          type="button"
          className="task-action-btn"
          title="Edit project"
          aria-label={`Edit ${project.name}`}
          onClick={(e) => {
            e.stopPropagation();
            onEdit(project);
          }}
        >
          <Pencil size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="task-action-btn task-action-btn--danger"
          title="Delete project"
          aria-label={`Delete ${project.name}`}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(project);
          }}
        >
          <Trash2 size={13} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
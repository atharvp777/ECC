import { Check, AlertTriangle, Folder, Clock } from "lucide-react";
import { formatMinutes, formatShortDate } from "../utils/format";

function deadlineLabel(deadline) {
  const d = new Date(deadline);
  if (Number.isNaN(d.getTime())) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  if (day.getTime() === today.getTime()) return "Due today";
  return formatShortDate(deadline);
}

/**
 * Reusable task row used by Overview today and available to the Tasks redesign.
 *
 * `task` is plain data: { id | task_id, title, priority, status?, deadline?,
 * estimated_minutes?, project_name? }. `onComplete` and `onOpen` are optional
 * callbacks; when omitted the row renders read-only.
 */
export default function TaskRow({
  task,
  onComplete,
  onOpen,
  showProject = true,
  showDeadline = true,
  showEstimate = true,
}) {
  const done = task.status === "done";
  const overdue = !done && task.deadline != null && new Date(task.deadline) < new Date();

  const handleOpenKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen?.(task);
    }
  };

  return (
    <div className="task-item">
      {onComplete ? (
        <button
          type="button"
          className={`task-check ${done ? "done" : ""}`}
          onClick={() => onComplete(task)}
          aria-label={done ? `Reopen ${task.title}` : `Complete ${task.title}`}
        >
          {done && <Check size={10} aria-hidden="true" />}
        </button>
      ) : (
        <span className={`task-check ${done ? "done" : ""}`} aria-hidden="true">
          {done && <Check size={10} />}
        </span>
      )}
      <div
        className="task-body"
        role={onOpen ? "button" : undefined}
        tabIndex={onOpen ? 0 : undefined}
        onClick={onOpen ? () => onOpen(task) : undefined}
        onKeyDown={onOpen ? handleOpenKeyDown : undefined}
      >
        <div className={`task-title ${done ? "done" : ""}`}>{task.title}</div>
        <div className="task-row__meta">
          <span className={`badge badge-${task.priority}`}>{task.priority}</span>
          {showProject && task.project_name && (
            <span className="task-row__meta-item">
              <Folder aria-hidden="true" />
              {task.project_name}
            </span>
          )}
          {showDeadline && task.deadline && (
            <span className={`task-row__meta-item ${overdue ? "overdue" : ""}`}>
              {overdue && <AlertTriangle aria-hidden="true" />}
              {overdue ? "Overdue" : deadlineLabel(task.deadline)}
            </span>
          )}
          {showEstimate && task.estimated_minutes != null && task.estimated_minutes > 0 && (
            <span className="task-row__meta-item">
              <Clock aria-hidden="true" />
              {formatMinutes(task.estimated_minutes)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
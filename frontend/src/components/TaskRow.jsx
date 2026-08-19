import { Check, AlertTriangle, Folder, Clock, CalendarDays } from "lucide-react";
import { formatMinutes, formatDeadline, formatOverdue, formatScheduled, isOverdue } from "../utils/format";

/**
 * Reusable task row used by Overview and the Tasks workspace.
 *
 * `task` is plain data: { id | task_id, title, priority, status?, deadline?,
 * estimated_minutes?, project_name?, google_calendar_event_id?,
 * scheduled_start/end?, calendar_sync_error? }.
 *
 * `onComplete`/`onOpen` are optional; when omitted the row renders read-only.
 * `onOpen(task, event)` lets the parent remember the trigger element so focus
 * can be restored when a drawer closes. `actions` is an optional node shown
 * on hover/focus in list contexts.
 */
export default function TaskRow({
  task,
  onComplete,
  onOpen,
  showProject = true,
  showPriority = true,
  showDeadline = true,
  showEstimate = true,
  showCalendar = false,
  overdueDays = false,
  actions,
}) {
  const done = task.status === "done";
  const overdue = isOverdue(task.deadline, done);
  const checkClass = [
    "task-check",
    done ? "done" : "",
    task.status === "in_progress" ? "task-check--in_progress" : "",
    task.status === "blocked" ? "task-check--blocked" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const glyph =
    task.status === "in_progress" ? (
      <span className="task-check__dot" aria-hidden="true" />
    ) : task.status === "blocked" ? (
      <span className="task-check__line" aria-hidden="true" />
    ) : done ? (
      <Check size={10} aria-hidden="true" />
    ) : null;

  return (
    <div className={`task-item${done ? " is-done" : ""}`}>
      {onComplete ? (
        <button
          type="button"
          className={checkClass}
          onClick={() => onComplete(task)}
          aria-label={done ? `Reopen ${task.title}` : `Complete ${task.title}`}
        >
          {glyph}
        </button>
      ) : (
        <span className={checkClass} aria-hidden="true">
          {glyph}
        </span>
      )}
      <div
        className="task-body"
        role={onOpen ? "button" : undefined}
        tabIndex={onOpen ? 0 : undefined}
        onClick={onOpen ? (e) => onOpen(task, e) : undefined}
        onKeyDown={
          onOpen
            ? (e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onOpen(task, e);
                }
              }
            : undefined
        }
      >
        <div className={`task-title ${done ? "done" : ""}`}>{task.title}</div>
        <div className="task-row__meta">
          {showPriority && task.priority && (
            <span className={`badge badge-${task.priority}`}>{task.priority}</span>
          )}
          {showProject && task.project_name && (
            <span className="task-row__meta-item">
              <Folder aria-hidden="true" />
              {task.project_name}
            </span>
          )}
          {showDeadline && task.deadline && (
            <span className={`task-row__meta-item ${overdue ? "overdue" : ""}`}>
              {overdue && <AlertTriangle aria-hidden="true" />}
              {overdue ? (overdueDays ? formatOverdue(task.deadline) : "Overdue") : formatDeadline(task.deadline)}
            </span>
          )}
          {showEstimate && task.estimated_minutes != null && task.estimated_minutes > 0 && (
            <span className="task-row__meta-item">
              <Clock aria-hidden="true" />
              {formatMinutes(task.estimated_minutes)}
            </span>
          )}
          {showCalendar && task.google_calendar_event_id && !task.calendar_sync_error && (
            <span className="task-row__meta-item">
              <CalendarDays aria-hidden="true" />
              {formatScheduled(task)}
            </span>
          )}
          {showCalendar && task.calendar_sync_error && (
            <span
              className="task-row__meta-item task-row__meta-item--warn"
              title={task.calendar_sync_error}
            >
              <AlertTriangle aria-hidden="true" />
              Calendar sync issue
            </span>
          )}
        </div>
      </div>
      {actions && <div className="task-actions">{actions}</div>}
    </div>
  );
}
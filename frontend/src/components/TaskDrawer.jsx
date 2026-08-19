import { useEffect, useRef, useState } from "react";
import {
  X,
  CalendarDays,
  CalendarPlus,
  CalendarX,
  RefreshCw,
  AlertTriangle,
  Sparkles,
  Trash2,
} from "lucide-react";
import { createTask, updateTask, linkTaskToCalendar, unlinkTaskFromCalendar } from "../api";
import OrbitButton from "./ui/OrbitButton";
import TaskForm, { STATUS_LABELS, TYPE_LABELS } from "./TaskForm";
import { formatMinutes, formatDeadline, formatOverdue, formatScheduled, dateTimeLabel, isOverdue } from "../utils/format";

/**
 * Right-side task drawer. Renders in three modes:
 *  - "new": compact creation form
 *  - "edit": TaskForm pre-filled from `task`
 *  - "view": details + complete/edit/delete/schedule/Ask Orbit
 *
 * Mutations call the API here and then `onReload()` so the parent refreshes
 * the task list (which flows back into this drawer via the `task` prop).
 * Inline errors are shown inside the drawer; no fake success.
 */
export default function TaskDrawer({
  task,
  initialMode = "view",
  projects,
  defaultProjectId = "",
  onClose,
  onReload,
  onCreated,
  onRequestDelete,
  onAskOrbit,
  triggerRef,
}) {
  const creating = initialMode === "new" || !task;
  const [internalMode, setInternalMode] = useState(initialMode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [editError, setEditError] = useState(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleForm, setScheduleForm] = useState({ date: "", time: "", duration: "60" });
  const closeBtnRef = useRef(null);

  useEffect(() => {
    if (!creating) {
      setInternalMode(initialMode);
    }
  }, [initialMode]);

  useEffect(() => {
    if (!creating) {
      setInternalMode("view");
      setError(null);
      setEditError(null);
      setScheduleOpen(false);
      closeBtnRef.current?.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  useEffect(() => {
    const onKey = (e) => {
      // Don't swallow Escape meant for an open confirm dialog.
      if (e.key === "Escape" && !document.querySelector(".modal-overlay")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    return () => {
      triggerRef?.current?.focus?.();
    };
  }, [triggerRef]);

  const complete = async () => {
    if (busy || !task) return;
    setBusy(true);
    setError(null);
    try {
      await updateTask(task.id, { status: task.status === "done" ? "todo" : "done" });
      setBusy(false);
      onReload();
    } catch {
      setBusy(false);
      setError("Couldn't update task.");
    }
  };

  const saveEdit = async (payload) => {
    if (!task) return;
    setBusy(true);
    setEditError(null);
    try {
      await updateTask(task.id, payload);
      setBusy(false);
      setInternalMode("view");
      onReload();
    } catch {
      setBusy(false);
      setEditError("Couldn't update task.");
    }
  };

  const create = async (payload) => {
    setBusy(true);
    setError(null);
    try {
      const created = await createTask(payload);
      setBusy(false);
      onCreated?.(created);
    } catch {
      setBusy(false);
      setError("Couldn't create task.");
    }
  };

  const addSchedule = async () => {
    if (busy || !task || !scheduleForm.date) return;
    setBusy(true);
    setError(null);
    try {
      await linkTaskToCalendar(task.id, {
        when: scheduleForm.date,
        start_time: scheduleForm.time || null,
        duration_minutes: parseInt(scheduleForm.duration, 10) || 60,
      });
      setBusy(false);
      setScheduleOpen(false);
      onReload();
    } catch {
      setBusy(false);
      setError("Couldn't schedule the task on your calendar.");
    }
  };

  const removeSchedule = async () => {
    if (busy || !task) return;
    setBusy(true);
    setError(null);
    try {
      await unlinkTaskFromCalendar(task.id);
      setBusy(false);
      onReload();
    } catch {
      setBusy(false);
      setError("Couldn't remove the calendar event.");
    }
  };

  const retrySync = async () => {
    if (busy || !task) return;
    setBusy(true);
    setError(null);
    try {
      await linkTaskToCalendar(task.id, {
        scheduled_start: task.scheduled_start || null,
        scheduled_end: task.scheduled_end || null,
        duration_minutes: 60,
      });
      setBusy(false);
      onReload();
    } catch {
      setBusy(false);
      setError("Couldn't sync the calendar event.");
    }
  };

  const linked = Boolean(task?.google_calendar_event_id);
  const deadline = task?.deadline ? (isOverdue(task.deadline, task.status === "done") ? formatOverdue(task.deadline) : formatDeadline(task.deadline)) : "No deadline";

  const meta = task
    ? [
        ["Status", STATUS_LABELS[task.status] || task.status],
        ["Priority", task.priority ? task.priority.toUpperCase() : "—"],
        ["Project", task.project_name || "No project"],
        ["Type", TYPE_LABELS[task.task_type] || task.task_type || "Work"],
        ["Deadline", deadline],
        ["Estimate", task.estimated_minutes != null ? formatMinutes(task.estimated_minutes) : "—"],
      ]
    : [];

  return (
    <div className="task-drawer-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-drawer" role="dialog" aria-modal="true" aria-label={task?.title || "New task"}>
        <div className="task-drawer__header">
          <h3 className="task-drawer__title">{task?.title || "New task"}</h3>
          <button
            ref={closeBtnRef}
            type="button"
            className="task-drawer__icon-btn"
            onClick={onClose}
            aria-label="Close task details"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        {creating || internalMode === "new" ? (
          <div className="task-drawer__body">
            {error && <p className="task-drawer__error" role="alert">{error}</p>}
            <TaskForm
              projects={projects}
              defaultProjectId={defaultProjectId}
              submitLabel="Add Task"
              showSchedule
              onSave={create}
              onCancel={onClose}
            />
          </div>
        ) : internalMode === "edit" ? (
          <div className="task-drawer__body">
            {editError && <p className="task-drawer__error" role="alert">{editError}</p>}
            <TaskForm
              projects={projects}
              initial={task}
              submitLabel="Save changes"
              onSave={saveEdit}
              onCancel={() => setInternalMode("view")}
            />
          </div>
        ) : (
          <div className="task-drawer__body">
            {error && <p className="task-drawer__error" role="alert">{error}</p>}

            <div className="task-drawer__meta">
              {meta.map(([label, value]) => (
                <div className="task-drawer__field" key={label}>
                  <span className="task-drawer__field-label">{label}</span>
                  <span className="task-drawer__field-value">{value}</span>
                </div>
              ))}
            </div>

            {task.description && (
              <div className="task-drawer__section">
                <span className="task-drawer__field-label">Description</span>
                <p className="task-drawer__description">{task.description}</p>
              </div>
            )}

            <div className="task-drawer__calendar">
              <span className="task-drawer__field-label">Calendar</span>
              {task.calendar_sync_error ? (
                <div className="task-drawer__cal-msg task-drawer__cal-msg--error">
                  <AlertTriangle size={13} aria-hidden="true" />
                  Calendar sync issue
                  <span className="task-drawer__cal-error">{task.calendar_sync_error}</span>
                </div>
              ) : linked ? (
                <div className="task-drawer__cal-msg">
                  <CalendarDays size={13} aria-hidden="true" />
                  {formatScheduled(task)}
                </div>
              ) : (
                <div className="task-drawer__cal-msg">
                  <CalendarDays size={13} aria-hidden="true" />
                  No calendar block
                </div>
              )}

              <div className="task-drawer__cal-actions">
                {linked ? (
                  <>
                    {task.calendar_sync_error && task.scheduled_start && (
                      <OrbitButton size="sm" variant="secondary" onClick={retrySync} loading={busy}>
                        <RefreshCw size={12} aria-hidden="true" /> Retry sync
                      </OrbitButton>
                    )}
                    <OrbitButton size="sm" variant="ghost" onClick={removeSchedule} loading={busy}>
                      <CalendarX size={12} aria-hidden="true" /> Remove from calendar
                    </OrbitButton>
                  </>
                ) : (
                  <OrbitButton
                    size="sm"
                    variant="secondary"
                    onClick={() => setScheduleOpen((o) => !o)}
                    aria-expanded={scheduleOpen}
                  >
                    <CalendarPlus size={12} aria-hidden="true" /> {scheduleOpen ? "Cancel" : "Schedule"}
                  </OrbitButton>
                )}
              </div>

              {!linked && scheduleOpen && (
                <div className="task-drawer__schedule">
                  <div className="task-drawer__schedule-row">
                    <input type="date" className="form-input" value={scheduleForm.date} onChange={(e) => setScheduleForm((f) => ({ ...f, date: e.target.value }))} aria-label="Schedule date" />
                    <input type="time" className="form-input" value={scheduleForm.time} onChange={(e) => setScheduleForm((f) => ({ ...f, time: e.target.value }))} aria-label="Schedule start time" />
                    <input type="number" min="1" className="form-input" value={scheduleForm.duration} onChange={(e) => setScheduleForm((f) => ({ ...f, duration: e.target.value }))} aria-label="Schedule duration (minutes)" placeholder="60" />
                  </div>
                  <OrbitButton size="sm" variant="primary" onClick={addSchedule} loading={busy} disabled={!scheduleForm.date}>
                    <CalendarPlus size={12} aria-hidden="true" /> Add to calendar
                  </OrbitButton>
                </div>
              )}
            </div>

            <div className="task-drawer__meta task-drawer__meta--compact">
              <div className="task-drawer__field">
                <span className="task-drawer__field-label">Created</span>
                <span className="task-drawer__field-value">{dateTimeLabel(task.created_at)}</span>
              </div>
              <div className="task-drawer__field">
                <span className="task-drawer__field-label">Updated</span>
                <span className="task-drawer__field-value">{dateTimeLabel(task.updated_at)}</span>
              </div>
            </div>

            <div className="task-drawer__footer">
              <OrbitButton size="sm" variant="primary" onClick={complete} loading={busy}>
                {task.status === "done" ? "Reopen" : "Complete"}
              </OrbitButton>
              <OrbitButton size="sm" variant="secondary" onClick={() => setInternalMode("edit")}>
                Edit
              </OrbitButton>
              <OrbitButton size="sm" variant="ghost" onClick={onAskOrbit}>
                <Sparkles size={12} aria-hidden="true" /> Ask Orbit
              </OrbitButton>
              <OrbitButton size="sm" variant="danger" onClick={() => onRequestDelete(task)}>
                <Trash2 size={12} aria-hidden="true" /> Delete
              </OrbitButton>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
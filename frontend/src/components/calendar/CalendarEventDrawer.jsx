import { useEffect, useRef, useState } from "react";
import { X, ExternalLink, CalendarX, RefreshCw, AlertTriangle, ShieldAlert } from "lucide-react";
import OrbitButton from "../ui/OrbitButton";
import { unlinkTaskFromCalendar, linkTaskToCalendar } from "../../api";
import { STATUS_LABELS } from "../TaskForm";
import { formatTime, formatShortDate, formatMinutes, formatDeadline, formatOverdue, isOverdue, formatScheduled } from "../../utils/format";

function Field({ label, children }) {
  return (
    <div className="task-drawer__field">
      <span className="task-drawer__field-label">{label}</span>
      <span className="task-drawer__field-value">{children || "—"}</span>
    </div>
  );
}

export default function CalendarEventDrawer({ event, canWrite, onClose, onReload, onOpenTask, triggerRef }) {
  const closeRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e) => {
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

  if (!event) return null;

  const timeRange = event.allDay ? "All day" : `${formatTime(event.start)}–${formatTime(event.end)}`;
  const deadline = event.task?.deadline
    ? isOverdue(event.task.deadline, event.task.status === "done")
      ? formatOverdue(event.task.deadline)
      : formatDeadline(event.task.deadline)
    : null;

  const removeFromCalendar = async () => {
    if (busy || !event.taskId) return;
    setBusy(true);
    setError(null);
    try {
      await unlinkTaskFromCalendar(event.taskId);
      setBusy(false);
      onReload();
    } catch {
      setBusy(false);
      setError("Couldn't remove the calendar event.");
    }
  };

  const retrySync = async () => {
    if (busy || !event.task) return;
    setBusy(true);
    setError(null);
    try {
      await linkTaskToCalendar(event.taskId, {
        scheduled_start: event.task.scheduled_start || null,
        scheduled_end: event.task.scheduled_end || null,
        duration_minutes: 60,
      });
      setBusy(false);
      onReload();
    } catch {
      setBusy(false);
      setError("Couldn't sync the calendar event.");
    }
  };

  const typeLabel = event.type === "google" ? "Google Calendar event" : event.type === "orbit" ? "Scheduled task" : "Deadline";
  const orbitLinked = Boolean(event.task?.google_calendar_event_id);

  return (
    <div className="task-drawer-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-drawer" role="dialog" aria-modal="true" aria-label={event.title}>
        <div className="task-drawer__header">
          <h3 className="task-drawer__title">{event.title}</h3>
          <button type="button" className="task-drawer__icon-btn" ref={closeRef} onClick={onClose} aria-label="Close event details">
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="task-drawer__body">
          <span className={`calendar-event-type calendar-event-type--${event.type}`}>{typeLabel}</span>

          {error && <p className="task-drawer__error" role="alert">{error}</p>}

          {event.type === "google" && (
            <div className="task-drawer__meta">
              <Field label="Date">{event.start ? formatShortDate(event.start) : null}</Field>
              <Field label="Time">{timeRange}</Field>
              <Field label="Location">{event.location}</Field>
              <Field label="Description">{event.description}</Field>
            </div>
          )}

          {event.type === "orbit" && (
            <>
              <div className="task-drawer__meta">
                <Field label="Project">{event.project}</Field>
                <Field label="Priority">{event.priority ? event.priority.toUpperCase() : null}</Field>
                <Field label="Status">{STATUS_LABELS[event.status] || event.status}</Field>
                <Field label="Estimate">{event.task?.estimated_minutes != null ? formatMinutes(event.task.estimated_minutes) : null}</Field>
                <Field label="Scheduled">{event.task ? formatScheduled(event.task) : timeRange}</Field>
                <Field label="Deadline">{deadline}</Field>
              </div>

              {!canWrite && (
                <div className="calendar-drawer__note">
                  <ShieldAlert size={13} aria-hidden="true" />
                  <span>Read-only calendar access — reconnect Google Calendar to edit events.</span>
                </div>
              )}

              {orbitLinked && event.task?.calendar_sync_error && (
                <div className="task-drawer__cal-msg task-drawer__cal-msg--error">
                  <AlertTriangle size={13} aria-hidden="true" />
                  <span className="task-drawer__cal-error">{event.task.calendar_sync_error}</span>
                </div>
              )}

              <div className="task-drawer__footer">
                <OrbitButton variant="secondary" size="sm" onClick={() => onOpenTask?.(event.task)}>Open task</OrbitButton>
                {canWrite && orbitLinked && (
                  <>
                    <OrbitButton variant="secondary" size="sm" onClick={retrySync} disabled={busy}>
                      <RefreshCw size={12} aria-hidden="true" /> Retry sync
                    </OrbitButton>
                    <OrbitButton variant="danger" size="sm" onClick={removeFromCalendar} disabled={busy}>
                      <CalendarX size={12} aria-hidden="true" /> Remove from calendar
                    </OrbitButton>
                  </>
                )}
              </div>
            </>
          )}

          {event.type === "deadline" && (
            <>
              <div className="task-drawer__meta">
                <Field label="Project">{event.project}</Field>
                <Field label="Priority">{event.priority ? event.priority.toUpperCase() : null}</Field>
                <Field label="Status">{STATUS_LABELS[event.status] || event.status}</Field>
                <Field label="Deadline">{deadline}</Field>
                <Field label="Estimate">{event.task?.estimated_minutes != null ? formatMinutes(event.task.estimated_minutes) : null}</Field>
              </div>
              <div className="task-drawer__footer">
                <OrbitButton variant="secondary" size="sm" onClick={() => onOpenTask?.(event.task)}>Open task</OrbitButton>
              </div>
            </>
          )}

          {event.htmlLink && (
            <a
              className="calendar-drawer__link"
              href={event.htmlLink}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={12} aria-hidden="true" /> Open in Google Calendar
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
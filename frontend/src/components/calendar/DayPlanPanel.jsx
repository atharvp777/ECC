import { useEffect, useRef } from "react";
import { X, Sparkles, RefreshCw, CalendarX, AlertTriangle } from "lucide-react";
import OrbitButton from "../ui/OrbitButton";
import OrbitSkeleton from "../ui/OrbitSkeleton";
import DayPlanBlock from "./DayPlanBlock";
import DayPlanUnscheduled from "./DayPlanUnscheduled";
import { formatMinutes, formatTime } from "../../utils/format";
import { API_BASE_URL } from "../../config";

const AUTH_URL = `${API_BASE_URL}/integrations/google/auth`;

function Section({ title, children }) {
  return (
    <div className="dayplan-section">
      <h4 className="dayplan-section__title">{title}</h4>
      {children}
    </div>
  );
}

export default function DayPlanPanel({
  plan,
  loading,
  error,
  onRetry,
  onClose,
  onSchedule,
  scheduling,
  stale,
  onReviewUpdated,
  triggerRef,
}) {
  const closeRef = useRef(null);

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

  const summary = plan?.summary || {};
  const blocks = plan?.scheduled_blocks || [];
  const unscheduled = plan?.unscheduled_tasks || [];
  const windows = plan?.unused_windows || [];
  const planned = formatMinutes(summary.total_scheduled_minutes);
  const available = formatMinutes(summary.total_available_minutes);

  return (
    <div className="task-drawer-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-drawer dayplan-panel" role="dialog" aria-modal="true" aria-label="Plan My Day">
        <div className="task-drawer__header">
          <h3 className="task-drawer__title">Plan My Day</h3>
          <button type="button" className="task-drawer__icon-btn" ref={closeRef} onClick={onClose} aria-label="Close day plan">
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="task-drawer__body">
          {loading && (
            <div className="dayplan-skeleton" aria-busy="true">
              {[0, 1, 2].map((i) => <OrbitSkeleton key={i} width="100%" height={44} />)}
            </div>
          )}

          {error && (
            <div className="dayplan-error" role="alert">
              <p>Couldn't load today's plan.</p>
              <OrbitButton size="sm" variant="secondary" onClick={onRetry}>
                <RefreshCw size={12} aria-hidden="true" /> Retry
              </OrbitButton>
            </div>
          )}

          {!loading && !error && plan && (
            <>
              <div className="dayplan-summary">
                {summary.total_tasks > 0 ? (
                  <>
                    <span>{summary.scheduled_tasks} of {summary.total_tasks} tasks scheduled</span>
                    {planned && <span aria-hidden="true">·</span>}
                    {planned && <span>{planned} planned</span>}
                    {available && <span aria-hidden="true">·</span>}
                    {available && <span>{available} available</span>}
                  </>
                ) : (
                  <span>Nothing to plan for today.</span>
                )}
              </div>

              {stale && (
                <div className="dayplan-stale" role="alert">
                  <AlertTriangle size={13} aria-hidden="true" />
                  <span>Your plan has changed since it was created.</span>
                  <OrbitButton size="sm" variant="secondary" onClick={onReviewUpdated}>
                    Review updated plan
                  </OrbitButton>
                </div>
              )}

              {blocks.length > 0 && (
                <Section title="Scheduled">
                  <ul className="dayplan-blocks">
                    {blocks.map((b, i) => <DayPlanBlock key={`${b.task_id}-${i}`} block={b} />)}
                  </ul>
                </Section>
              )}

              {windows.length > 0 && (
                <Section title="Available time">
                  <ul className="dayplan-windows">
                    {windows.map((w, i) => (
                      <li className="dayplan-window" key={i}>
                        <span className="dayplan-window__time">{formatTime(w.start)}–{formatTime(w.end)}</span>
                        <span className="dayplan-window__duration">{formatMinutes(w.duration_minutes)}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {unscheduled.length > 0 && (
                <Section title="Not scheduled">
                  <ul className="dayplan-unscheduled-list">
                    {unscheduled.map((t, i) => <DayPlanUnscheduled key={`${t.task_id}-${i}`} task={t} />)}
                  </ul>
                </Section>
              )}

              {!summary.calendar_connected && (
                <div className="calendar-conn calendar-conn--notice">
                  <CalendarX size={14} aria-hidden="true" />
                  <span>Connect Google Calendar to see your schedule here.</span>
                  <a className="orbit-btn orbit-btn--secondary orbit-btn--sm" href={AUTH_URL} target="_blank" rel="noreferrer">
                    Connect Google Calendar
                  </a>
                </div>
              )}

              <div className="task-drawer__footer">
                <OrbitButton variant="primary" size="md" onClick={onSchedule} loading={scheduling}>
                  <Sparkles size={14} aria-hidden="true" /> Schedule this plan with Orbit
                </OrbitButton>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
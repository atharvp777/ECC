import { CalendarCheck, CalendarX, RefreshCw, ShieldAlert } from "lucide-react";
import OrbitButton from "../ui/OrbitButton";
import OrbitBadge from "../ui/OrbitBadge";
import OrbitSkeleton from "../ui/OrbitSkeleton";
import { API_BASE_URL } from "../../config";

const AUTH_URL = `${API_BASE_URL}/integrations/google/auth`;

/**
 * Connection state line for the Calendar workspace.
 *
 * States: loading | error | not connected | read-only | connected.
 * Every state carries explicit text plus an icon — never color alone.
 */
export default function CalendarConnectionState({ status, loading, error, onRetry }) {
  if (loading && !status) {
    return (
      <div className="calendar-conn" aria-busy="true">
        <OrbitSkeleton width={220} height={14} shape="text" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="calendar-conn calendar-conn--error" role="alert">
        <CalendarX size={14} aria-hidden="true" />
        <span>Calendar couldn't be loaded.</span>
        <OrbitButton size="sm" variant="secondary" onClick={onRetry}>
          <RefreshCw size={12} aria-hidden="true" /> Retry
        </OrbitButton>
      </div>
    );
  }

  if (!status?.google_calendar) {
    return (
      <div className="calendar-conn calendar-conn--notice">
        <CalendarX size={14} aria-hidden="true" />
        <span>Connect Google Calendar to see your schedule here.</span>
        <a className="orbit-btn orbit-btn--secondary orbit-btn--sm" href={AUTH_URL} target="_blank" rel="noreferrer">
          Connect Google Calendar
        </a>
      </div>
    );
  }

  if (!status.google_calendar_can_write) {
    return (
      <div className="calendar-conn calendar-conn--notice">
        <ShieldAlert size={14} aria-hidden="true" />
        <span>Read-only calendar access — reconnect to write events.</span>
        <a className="orbit-btn orbit-btn--secondary orbit-btn--sm" href={AUTH_URL} target="_blank" rel="noreferrer">
          Reconnect Google Calendar
        </a>
      </div>
    );
  }

  return (
    <div className="calendar-conn">
      <OrbitBadge variant="success">
        <CalendarCheck size={12} aria-hidden="true" /> Connected
      </OrbitBadge>
      <span className="calendar-conn__hint">Syncing with Google Calendar</span>
    </div>
  );
}
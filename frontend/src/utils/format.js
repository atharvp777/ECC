const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Format minutes as "45m", "1h", or "1h 20m". Returns null when unset/zero. */
export function formatMinutes(minutes) {
  if (minutes == null || minutes <= 0) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/** Short date like "Aug 24" (deterministic, not locale-dependent). */
export function formatShortDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

/** Wall-clock time like "09:00" (24h). Returns null when invalid/unset. */
export function formatTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function startOfDay(iso) {
  const d = new Date(iso);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** True when a not-done task's deadline has already passed. */
export function isOverdue(iso, done = false) {
  if (done || !iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d < new Date();
}

/** "Due today" or a short date like "Aug 24". Returns null when unset/invalid. */
export function formatDeadline(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  if (startOfDay(iso).getTime() === startOfDay(new Date().toISOString()).getTime()) return "Due today";
  return formatShortDate(iso);
}

/** "2 days overdue" (calendar-day diff). Falls back to "Overdue" for <1 day. */
export function formatOverdue(iso) {
  if (!iso) return "Overdue";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Overdue";
  const days = Math.round((startOfDay(new Date().toISOString()) - startOfDay(iso)) / 86400000);
  if (days < 1) return "Overdue";
  return days === 1 ? "1 day overdue" : `${days} days overdue`;
}

/** "Scheduled Aug 21 · 10:00–11:00" from a task's scheduled_start/end. */
export function formatScheduled(task = {}) {
  const date = formatShortDate(task.scheduled_start);
  const start = formatTime(task.scheduled_start);
  const end = formatTime(task.scheduled_end);
  if (date && start && end) return `Scheduled ${date} · ${start}–${end}`;
  if (date) return `Scheduled ${date}`;
  return "Scheduled";
}

/** "Aug 21 · 10:00" for created/updated metadata. Falls back to "—". */
export function dateTimeLabel(iso) {
  const date = formatShortDate(iso);
  if (!date) return "—";
  const time = formatTime(iso);
  return time ? `${date} · ${time}` : date;
}
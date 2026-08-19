const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function addDays(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

export function startOfWeek(date) {
  const d = startOfDay(date);
  const offset = (d.getDay() + 6) % 7;
  return addDays(d, -offset);
}

export function isSameDay(a, b) {
  if (!a || !b) return false;
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function isToday(date) {
  return isSameDay(date, new Date());
}

export function minutesFromMidnight(date) {
  return date.getHours() * 60 + date.getMinutes();
}

export function hourLabels() {
  return Array.from({ length: 24 }, (_, i) => i);
}

export function formatHour(hour) {
  if (hour === 0) return "12 AM";
  if (hour === 12) return "12 PM";
  return hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
}

export function parseEventStart(value) {
  if (!value) return null;
  if (typeof value === "string" && !value.includes("T")) {
    const parts = value.split("-").map(Number);
    if (parts.length === 3 && parts.every(Number.isFinite)) {
      const dt = new Date(parts[0], parts[1] - 1, parts[2]);
      return Number.isNaN(dt.getTime()) ? null : dt;
    }
  }
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

export function weekRange(anchor) {
  const start = startOfWeek(anchor);
  return { start, end: addDays(start, 6) };
}

export function monthGrid(anchor) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const gridStart = startOfWeek(first);
  return { gridStart, days: Array.from({ length: 42 }, (_, i) => addDays(gridStart, i)) };
}

export function formatDayHeader(date) {
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

export function formatWeekRange(anchor) {
  const { start, end } = weekRange(anchor);
  const sameMonth = start.getMonth() === end.getMonth();
  if (sameMonth) return `${formatDayHeader(start)} – ${formatDayHeader(end)}`;
  return `${formatDayHeader(start)} – ${formatDayHeader(end)} ${end.getFullYear()}`;
}

export function formatDayLabel(date) {
  return `${WEEKDAYS[(date.getDay() + 6) % 7]}, ${formatDayHeader(date)}`;
}

export function formatMonthLabel(anchor) {
  return `${MONTHS[anchor.getMonth()]} ${anchor.getFullYear()}`;
}

export function sameDayEnd(start, end) {
  const dayEnd = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 23, 59, 59, 999);
  return end && end <= dayEnd ? end : dayEnd;
}

export function eventTop(event) {
  if (!event.start) return 0;
  return Math.max(0, (minutesFromMidnight(event.start) / 1440) * 100);
}

export function eventHeight(event) {
  if (!event.start || !event.end) return 0;
  const end = sameDayEnd(event.start, event.end);
  const minutes = Math.max(15, (end - event.start) / 60000);
  return Math.min(100, Math.max(1.5, (minutes / 1440) * 100));
}

export function buildCalendarEvents({ googleEvents = [], tasks = [], projects = [] }) {
  const projectNames = new Map(projects.map((p) => [p.id, p.name]));
  const linkedIds = new Set(
    tasks.filter((t) => t.google_calendar_event_id).map((t) => t.google_calendar_event_id)
  );
  const events = [];

  googleEvents.forEach((e, i) => {
    if (e.id && linkedIds.has(e.id)) return;
    events.push({
      key: `g-${e.id || i}`,
      type: "google",
      title: e.title || "(no title)",
      start: parseEventStart(e.start),
      end: parseEventStart(e.end),
      allDay: Boolean(e.all_day),
      location: e.location || null,
      description: e.description || null,
      htmlLink: e.html_link || null,
    });
  });

  tasks.forEach((t) => {
    if (t.scheduled_start && t.scheduled_end) {
      events.push({
        key: `o-${t.id}`,
        type: "orbit",
        title: t.title,
        start: parseEventStart(t.scheduled_start),
        end: parseEventStart(t.scheduled_end),
        allDay: false,
        project: projectNames.get(t.project_id) || null,
        taskId: t.id,
        priority: t.priority,
        status: t.status,
        task: t,
      });
    }
  });

  tasks.forEach((t) => {
    if (t.status !== "done" && t.deadline) {
      const start = parseEventStart(t.deadline);
      if (!start) return;
      events.push({
        key: `d-${t.id}`,
        type: "deadline",
        title: t.title,
        start,
        end: new Date(start.getTime() + 60 * 60000),
        allDay: false,
        project: projectNames.get(t.project_id) || null,
        taskId: t.id,
        priority: t.priority,
        status: t.status,
        task: t,
      });
    }
  });

  return events;
}

export function eventsOnDay(events, day) {
  return events.filter((e) => e.start && isSameDay(e.start, day));
}

export function planSignature(plan) {
  const blocks = plan?.scheduled_blocks || [];
  return blocks.map((b) => `${b.task_id}:${b.start}:${b.end}`).join("|");
}

export function unscheduledReason(reason) {
  if (reason === "needs_time_estimate") return "Needs a time estimate";
  if (reason === "no_available_calendar_window") return "No available calendar window";
  if (reason === "insufficient_remaining_time") return "Not enough remaining time";
  return reason || "Couldn't be scheduled";
}
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { formatTime, isOverdue } from "../../utils/format";
import { eventTop, eventHeight, isToday } from "../../utils/calendar";

function timeLabel(event) {
  const start = formatTime(event.start);
  const end = formatTime(event.end);
  if (event.allDay) return "All day";
  if (start && end) return `${start}–${end}`;
  return start || "";
}

function labelFor(event) {
  const base = event.allDay ? `${event.title} (all day)` : `${event.title}, ${timeLabel(event)}`;
  return event.project ? `${base}, ${event.project}` : base;
}

export default function CalendarEvent({ event, mode = "timed", onSelect, showToday = false }) {
  const overdue = event.type === "deadline" && isOverdue(event.start, event.status === "done");
  const classes = [
    "calendar-event",
    `calendar-event--${event.type}`,
    overdue ? "calendar-event--overdue" : "",
    showToday && isToday(event.start) ? "calendar-event--today" : "",
    mode === "chip" ? "calendar-event--chip" : "calendar-event--timed",
  ].filter(Boolean).join(" ");

  const style =
    mode === "timed" && !event.allDay
      ? { top: `${eventTop(event)}%`, height: `${eventHeight(event)}%` }
      : undefined;

  return (
    <button
      type="button"
      className={classes}
      style={style}
      onClick={(e) => onSelect?.(event, e.currentTarget)}
      aria-label={labelFor(event)}
    >
      {event.type === "deadline" && (
        <span className="calendar-event__type-icon" aria-hidden="true">
          <AlertTriangle size={11} />
        </span>
      )}
      {event.type === "orbit" && (
        <span className="calendar-event__type-icon" aria-hidden="true">
          <CheckCircle2 size={11} />
        </span>
      )}
      <span className="calendar-event__text">
        <span className="calendar-event__title">{event.title}</span>
        <span className="calendar-event__time">{timeLabel(event)}</span>
      </span>
    </button>
  );
}
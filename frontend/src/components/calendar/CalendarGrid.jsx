import CalendarEvent from "./CalendarEvent";
import { hourLabels, formatHour, eventsOnDay, isToday, formatDayHeader } from "../../utils/calendar";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/**
 * Timeline grid used by both the Week view (7 days) and the Day view (1 day).
 * Days map to columns; timed events are positioned absolutely inside their
 * day column against a 24-hour axis.
 */
export default function CalendarGrid({ days, events, onSelect }) {
  return (
    <div className="calendar-grid" role="grid" aria-label="Calendar grid">
      <div className="calendar-grid__header" role="row">
        <div className="calendar-grid__corner" aria-hidden="true" />
        {days.map((day) => (
          <div className="calendar-grid__day-head" role="columnheader" key={day.toISOString()}>
            <span className="calendar-grid__weekday">{WEEKDAYS[(day.getDay() + 6) % 7]}</span>
            <span className={`calendar-grid__date ${isToday(day) ? "calendar-grid__date--today" : ""}`}>
              {formatDayHeader(day)}
            </span>
          </div>
        ))}
      </div>

      <div className="calendar-grid__allday">
        <div className="calendar-grid__corner" aria-hidden="true" />
        {days.map((day) => (
          <div className="calendar-grid__allday-col" key={day.toISOString()}>
            {eventsOnDay(events, day)
              .filter((e) => e.allDay)
              .map((e) => (
                <CalendarEvent key={e.key} event={e} mode="chip" onSelect={onSelect} />
              ))}
          </div>
        ))}
      </div>

      <div className="calendar-grid__body">
        <div className="calendar-grid__times" aria-hidden="true">
          {hourLabels().map((h) => (
            <div className="calendar-grid__hour" key={h}>{formatHour(h)}</div>
          ))}
        </div>
        <div className="calendar-grid__days">
          {days.map((day) => (
            <div
              className={`calendar-grid__day ${isToday(day) ? "calendar-grid__day--today" : ""}`}
              key={day.toISOString()}
            >
              {eventsOnDay(events, day)
                .filter((e) => !e.allDay)
                .map((e) => (
                  <CalendarEvent key={e.key} event={e} onSelect={onSelect} />
                ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
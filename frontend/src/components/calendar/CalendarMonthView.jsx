import CalendarEvent from "./CalendarEvent";
import { monthGrid, eventsOnDay, isToday } from "../../utils/calendar";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_VISIBLE = 3;

export default function CalendarMonthView({ anchor, events, onSelect, onSelectDay }) {
  const { days } = monthGrid(anchor);
  const monthStart = new Date(anchor.getFullYear(), anchor.getMonth(), 1);

  return (
    <div className="calendar-month" role="grid" aria-label="Month view">
      <div className="calendar-month__header" role="row">
        {WEEKDAYS.map((d) => (
          <div className="calendar-month__head" role="columnheader" key={d}>{d}</div>
        ))}
      </div>
      <div className="calendar-month__body">
        {days.map((day) => {
          const dayEvents = eventsOnDay(events, day);
          const inMonth = day.getMonth() === monthStart.getMonth();
          const extra = dayEvents.length - MAX_VISIBLE;
          return (
            <div
              className={`calendar-month__cell ${inMonth ? "" : "calendar-month__cell--muted"} ${isToday(day) ? "calendar-month__cell--today" : ""}`}
              key={day.toISOString()}
            >
              <button
                type="button"
                className="calendar-month__date"
                onClick={() => onSelectDay?.(day)}
                aria-label={`Go to day view for ${day.toISOString()}`}
              >
                {day.getDate()}
              </button>
              <div className="calendar-month__events">
                {dayEvents.slice(0, MAX_VISIBLE).map((e) => (
                  <CalendarEvent key={e.key} event={e} mode="chip" onSelect={onSelect} />
                ))}
                {extra > 0 && (
                  <button
                    type="button"
                    className="calendar-month__more"
                    onClick={() => onSelectDay?.(day)}
                  >
                    +{extra} more
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
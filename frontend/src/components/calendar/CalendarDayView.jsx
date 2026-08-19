import CalendarGrid from "./CalendarGrid";

export default function CalendarDayView({ date, events, onSelect }) {
  return (
    <div className="calendar-day-view">
      <CalendarGrid days={[date]} events={events} onSelect={onSelect} />
    </div>
  );
}
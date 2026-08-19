import { ChevronLeft, ChevronRight, CalendarDays, Sparkles } from "lucide-react";
import OrbitButton from "../ui/OrbitButton";
import { formatWeekRange, formatDayLabel, formatMonthLabel } from "../../utils/calendar";

const VIEWS = ["week", "day", "month"];

export default function CalendarToolbar({ view, onViewChange, anchor, onPrev, onNext, onToday, onPlanDay, planBtnRef }) {
  const label = view === "week" ? formatWeekRange(anchor) : view === "day" ? formatDayLabel(anchor) : formatMonthLabel(anchor);

  return (
    <div className="calendar-toolbar">
      <div className="calendar-toolbar__group">
        <OrbitButton variant="secondary" size="sm" onClick={onToday}>Today</OrbitButton>
        <div className="calendar-toolbar__nav">
          <OrbitButton variant="ghost" size="sm" aria-label={`Previous ${view}`} onClick={onPrev}>
            <ChevronLeft size={16} aria-hidden="true" />
          </OrbitButton>
          <OrbitButton variant="ghost" size="sm" aria-label={`Next ${view}`} onClick={onNext}>
            <ChevronRight size={16} aria-hidden="true" />
          </OrbitButton>
        </div>
        <span className="calendar-toolbar__range" aria-live="polite">{label}</span>
      </div>

      <div className="calendar-toolbar__group">
        <div className="calendar-toolbar__views" role="group" aria-label="Calendar view">
          {VIEWS.map((v) => (
            <button
              key={v}
              type="button"
              className={`calendar-toolbar__view ${view === v ? "calendar-toolbar__view--active" : ""}`}
              aria-pressed={view === v}
              onClick={() => onViewChange(v)}
            >
              {v === "week" ? "Week" : v === "day" ? "Day" : "Month"}
            </button>
          ))}
        </div>
        <OrbitButton variant="secondary" size="sm" onClick={onPlanDay} ref={planBtnRef}>
          <CalendarDays size={14} aria-hidden="true" />
          <span className="calendar-toolbar__plan-label">Plan My Day</span>
          <Sparkles size={12} className="calendar-toolbar__plan-mark" aria-hidden="true" />
        </OrbitButton>
      </div>
    </div>
  );
}
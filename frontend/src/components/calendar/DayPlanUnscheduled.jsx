import { formatMinutes } from "../../utils/format";
import { unscheduledReason } from "../../utils/calendar";

export default function DayPlanUnscheduled({ task }) {
  return (
    <li className="dayplan-unscheduled">
      <div className="dayplan-unscheduled__row">
        <span className="dayplan-unscheduled__title">{task.title}</span>
        {task.estimated_minutes != null && (
          <span className="dayplan-unscheduled__estimate">{formatMinutes(task.estimated_minutes)}</span>
        )}
      </div>
      <span className="dayplan-unscheduled__reason">{unscheduledReason(task.reason)}</span>
    </li>
  );
}
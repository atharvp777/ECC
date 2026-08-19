import { formatTime, formatMinutes } from "../../utils/format";

export default function DayPlanBlock({ block }) {
  return (
    <li className="dayplan-block">
      <span className="dayplan-block__time">
        {formatTime(block.start)}–{formatTime(block.end)}
      </span>
      <span className="dayplan-block__main">
        <span className="dayplan-block__title">{block.title}</span>
        {block.project && <span className="dayplan-block__project">{block.project}</span>}
      </span>
      <span className="dayplan-block__duration">{formatMinutes(block.duration_minutes)}</span>
    </li>
  );
}
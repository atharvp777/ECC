const KIND_LABELS = {
  "task-created": "Task created",
  "task-updated": "Task updated",
  "task-completed": "Task completed",
  "task-deleted": "Task deleted",
  "calendar-event-created": "Calendar event created",
  "day-plan-scheduled": "Day plan scheduled",
  "day-plan-ready": "Day plan ready",
  "project-created": "Project created",
  "project-updated": "Project updated",
};

export default function ChatActionCard({ card, onNavigate, onConfirm }) {
  const kindLabel = KIND_LABELS[card.kind] || "Action";

  return (
    <div className="orbit-chat__card" role="group" aria-label={kindLabel}>
      <div className="orbit-chat__card-kind">{kindLabel}</div>
      <div className="orbit-chat__card-title">{card.title}</div>
      {card.meta && <div className="orbit-chat__card-meta">{card.meta}</div>}
      {card.blocks && card.blocks.length > 0 && (
        <ul className="orbit-chat__card-blocks">
          {card.blocks.map((block, index) => (
            <li key={index} className="orbit-chat__card-block">
              <span className="orbit-chat__card-block-time">
                {block.start}-{block.end}
              </span>
              <span className="orbit-chat__card-block-title">{block.title}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="orbit-chat__card-actions">
        {card.confirm && (
          <button
            type="button"
            className="orbit-btn orbit-btn--primary orbit-btn--sm"
            onClick={() => onConfirm(card)}
          >
            {card.confirm}
          </button>
        )}
        {card.nav &&
          card.nav.map((nav) => (
            <button
              key={nav.label}
              type="button"
              className="orbit-btn orbit-btn--secondary orbit-btn--sm"
              onClick={() => onNavigate(nav.to)}
            >
              {nav.label}
            </button>
          ))}
      </div>
    </div>
  );
}
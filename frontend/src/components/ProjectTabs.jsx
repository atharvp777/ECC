import { useRef } from "react";
import { useNavigate } from "react-router-dom";

const TABS = [
  ["overview", "Overview", ""],
  ["tasks", "Tasks", "/tasks"],
  ["documents", "Documents", "/documents"],
  ["notes", "Notes", "/notes"],
  ["ai", "Orbit AI", "/ai"],
];

/**
 * Route-driven workspace tabs. The active tab mirrors the URL
 * (/projects/:id, /projects/:id/tasks, …). Full keyboard arrow support.
 */
export default function ProjectTabs({ projectId, active }) {
  const navigate = useNavigate();
  const refs = useRef({});

  const go = (key, suffix) => navigate(`/projects/${projectId}${suffix}`);

  const onKeyDown = (e, index) => {
    let next = null;
    if (e.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    if (next == null) return;
    e.preventDefault();
    const [key, , suffix] = TABS[next];
    refs.current[key]?.focus();
    go(key, suffix);
  };

  return (
    <div className="project-tabs" role="tablist" aria-label="Project workspace">
      {TABS.map(([key, label, suffix], index) => {
        const selected = active === key;
        return (
          <button
            key={key}
            ref={(el) => {
              refs.current[key] = el;
            }}
            type="button"
            role="tab"
            id={`project-tab-${key}`}
            aria-selected={selected}
            aria-controls="project-panel"
            tabIndex={selected ? 0 : -1}
            className={`project-tabs__tab${selected ? " is-active" : ""}`}
            onClick={() => go(key, suffix)}
            onKeyDown={(e) => onKeyDown(e, index)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
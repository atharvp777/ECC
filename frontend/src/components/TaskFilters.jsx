import { PRIORITIES, TASK_TYPES, TYPE_LABELS } from "./TaskForm";

/**
 * Compact composable filters for the Tasks workspace: status segmented control,
 * priority/project/type selects, and a reset that appears when anything is
 * active. All filtering is client-side over the loaded task list.
 */
export default function TaskFilters({
  status,
  priority,
  project,
  type,
  projects,
  active,
  onStatusChange,
  onPriorityChange,
  onProjectChange,
  onTypeChange,
  onReset,
}) {
  return (
    <div className="tasks-filters">
      <div className="tasks-filters__row">
        <div className="tasks-segmented" role="group" aria-label="Status filter">
          {[
            ["all", "All"],
            ["active", "Active"],
            ["completed", "Completed"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={status === value ? "is-active" : ""}
              aria-pressed={status === value}
              onClick={() => onStatusChange(value)}
            >
              {label}
            </button>
          ))}
        </div>

        <select className="tasks-select" aria-label="Filter by priority" value={priority} onChange={(e) => onPriorityChange(e.target.value)}>
          <option value="all">All priorities</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p.toUpperCase()}</option>
          ))}
        </select>

        <select className="tasks-select" aria-label="Filter by project" value={project} onChange={(e) => onProjectChange(e.target.value)}>
          <option value="all">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={String(p.id)}>{p.name}</option>
          ))}
        </select>

        <select className="tasks-select" aria-label="Filter by type" value={type} onChange={(e) => onTypeChange(e.target.value)}>
          <option value="all">All types</option>
          {TASK_TYPES.map((t) => (
            <option key={t} value={t}>{TYPE_LABELS[t]}</option>
          ))}
        </select>

        {active && (
          <button type="button" className="tasks-filters__reset" onClick={onReset}>
            Clear filters
          </button>
        )}
      </div>
    </div>
  );
}
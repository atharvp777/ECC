import TaskRow from "./TaskRow";

/**
 * A labelled group of task rows in the Tasks workspace. Groups are rendered
 * only when non-empty. `actionsFor(task)` optionally provides per-row hover
 * actions (edit/delete shortcuts).
 */
export default function TaskGroup({ label, overdue = false, tasks, onComplete, onOpen, actionsFor }) {
  if (tasks.length === 0) return null;
  return (
    <section className="task-group" aria-label={label}>
      <h3 className={`task-group__title${overdue ? " task-group__title--overdue" : ""}`}>
        {label}
        <span className="task-group__count">{tasks.length}</span>
      </h3>
      <div className="tasks-list">
        {tasks.map((task) => (
          <TaskRow
            key={task.id ?? task.task_id}
            task={task}
            onComplete={onComplete}
            onOpen={onOpen}
            showCalendar
            overdueDays
            actions={actionsFor?.(task)}
          />
        ))}
      </div>
    </section>
  );
}
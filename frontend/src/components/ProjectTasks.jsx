import { Plus } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import OrbitEmptyState from "./ui/OrbitEmptyState";
import TaskGroup from "./TaskGroup";
import { ListChecks } from "lucide-react";

const PRIORITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 };

function compareOpen(a, b) {
  const ap = PRIORITY_RANK[a.priority] ?? 3;
  const bp = PRIORITY_RANK[b.priority] ?? 3;
  if (ap !== bp) return ap - bp;
  const at = a.deadline ? new Date(a.deadline).getTime() : Infinity;
  const bt = b.deadline ? new Date(b.deadline).getTime() : Infinity;
  if (at !== bt) return at - bt;
  return (a.id ?? a.task_id) - (b.id ?? b.task_id);
}

function compareDone(a, b) {
  const at = new Date(a.completed_at || a.updated_at || 0).getTime();
  const bt = new Date(b.completed_at || b.updated_at || 0).getTime();
  return bt - at || (b.id ?? b.task_id) - (a.id ?? a.task_id);
}

/**
 * Scoped task view for a project workspace. Renders only the tasks belonging
 * to this project (filtered upstream) and reuses TaskRow/TaskGroup from the
 * global workspace. Global Tasks remains the canonical management surface.
 */
export default function ProjectTasks({ tasks, onComplete, onOpenTask, actionsFor, onNewTask }) {
  const open = tasks.filter((t) => t.status !== "done").sort(compareOpen);
  const done = tasks.filter((t) => t.status === "done").sort(compareDone);

  return (
    <div className="project-tasks">
      {tasks.length === 0 ? (
        <OrbitEmptyState
          icon={ListChecks}
          title="No tasks in this project yet."
          description="Add your first task to track work here."
          action={
            <OrbitButton variant="secondary" onClick={onNewTask}>
              <Plus size={14} aria-hidden="true" /> Add task
            </OrbitButton>
          }
        />
      ) : (
        <>
          <TaskGroup
            label="Open"
            tasks={open}
            onComplete={onComplete}
            onOpen={onOpenTask}
            actionsFor={actionsFor}
          />
          <TaskGroup
            label="Completed"
            tasks={done}
            onComplete={onComplete}
            onOpen={onOpenTask}
            actionsFor={actionsFor}
          />
        </>
      )}
    </div>
  );
}
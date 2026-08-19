import OrbitBadge from "./ui/OrbitBadge";
import TaskRow from "./TaskRow";
import {
  CATEGORY_LABELS,
  STATUS_LABELS,
  STATUS_BADGE,
  formatProjectDeadline,
  projectPercent,
} from "../utils/projects";
import { formatShortDate } from "../utils/format";

/**
 * Overview tab for a project workspace: summary + progress + deadline, plus
 * compact previews of tasks, documents, and notes with quick links into each
 * tab. Not a duplicate of the global pages — just scoped snapshots.
 */
export default function ProjectOverview({ project, tasks, docs, notes, onNavigate }) {
  const open = tasks.filter((t) => t.status !== "done").length;
  const completed = tasks.length - open;
  const pct = projectPercent(project.done_tasks, project.task_count);
  const deadline = formatProjectDeadline(project.deadline);
  const recentTasks = [...tasks].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 3);

  return (
    <div className="project-overview">
      <section className="orbit-card project-overview__summary" aria-label="Project summary">
        <div className="project-overview__summary-row">
          <OrbitBadge variant={STATUS_BADGE[project.status] || "default"}>
            {STATUS_LABELS[project.status] || project.status}
          </OrbitBadge>
          <span className="project-overview__meta">
            {CATEGORY_LABELS[project.category] || project.category}
          </span>
          {deadline && (
            <span className={`project-overview__meta${deadline.startsWith("Overdue") ? " project-overview__meta--overdue" : ""}`}>
              {deadline}
            </span>
          )}
        </div>

        <div className="project-overview__progress">
          <div className="project-overview__progress-label">
            {project.task_count === 0 ? (
              <span className="project-overview__no-tasks">No tasks yet</span>
            ) : (
              <span>{project.done_tasks || 0} / {project.task_count} completed</span>
            )}
            {pct != null && <span className="project-overview__percent">{pct}%</span>}
          </div>
          {project.task_count > 0 && (
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${pct}%`, background: project.color }} />
            </div>
          )}
        </div>
      </section>

      <div className="project-overview__grid">
        <section className="overview-section" aria-label="Tasks">
          <div className="overview-section__header">
            <h3>Tasks</h3>
            <button type="button" className="overview-section__link" onClick={() => onNavigate("tasks")}>
              View tasks
            </button>
          </div>
          <div className="project-overview__count">{open} open · {completed} completed</div>
          {recentTasks.length > 0 ? (
            <div className="project-overview__tasks">
              {recentTasks.map((task) => (
                <TaskRow key={task.id ?? task.task_id} task={task} showProject={false} showCalendar />
              ))}
            </div>
          ) : (
            <p className="project-overview__hint">No tasks in this project yet.</p>
          )}
        </section>

        <section className="overview-section" aria-label="Documents">
          <div className="overview-section__header">
            <h3>Documents</h3>
            <button type="button" className="overview-section__link" onClick={() => onNavigate("documents")}>
              View documents
            </button>
          </div>
          <div className="project-overview__count">{docs.length} document{docs.length === 1 ? "" : "s"}</div>
          {docs.length > 0 && (
            <ul className="project-overview__list">
              {docs.slice(0, 3).map((doc) => (
                <li key={doc.id} className="project-overview__list-item">
                  <span className="project-overview__list-name">{doc.title || doc.original_filename}</span>
                  <span className="project-overview__list-date">{formatShortDate(doc.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
          {docs.length === 0 && <p className="project-overview__hint">No documents yet.</p>}
        </section>

        <section className="overview-section" aria-label="Notes">
          <div className="overview-section__header">
            <h3>Notes</h3>
            <button type="button" className="overview-section__link" onClick={() => onNavigate("notes")}>
              View notes
            </button>
          </div>
          <div className="project-overview__count">{notes.length} note{notes.length === 1 ? "" : "s"}</div>
          {notes.length > 0 && (
            <ul className="project-overview__list">
              {notes.slice(0, 3).map((note) => (
                <li key={note.id} className="project-overview__list-item">
                  <span className="project-overview__list-name">{note.title || "Untitled note"}</span>
                  <span className="project-overview__list-date">{formatShortDate(note.updated_at)}</span>
                </li>
              ))}
            </ul>
          )}
          {notes.length === 0 && <p className="project-overview__hint">No notes yet.</p>}
        </section>
      </div>
    </div>
  );
}
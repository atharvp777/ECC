const MAX_TASK_ROWS = 3;

export default function ChatContextPanel({
  open = false,
  loading,
  projects,
  tasks,
  documents,
  calendarConnected,
  onNavigate,
  onOpenProject,
  onClose,
}) {
  const openTasks = tasks.filter((task) => task.status !== "done");

  return (
    <aside
      id="orbit-chat-context"
      className={`orbit-chat__context${open ? " orbit-chat__context--open" : ""}`}
      aria-label="Context"
    >
      <div className="orbit-chat__context-head">
        <h3 className="orbit-chat__context-title">Context</h3>
        <button
          type="button"
          className="orbit-chat__context-close"
          aria-label="Close context panel"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      <section className="orbit-chat__context-section">
        <div className="orbit-chat__context-heading">Projects</div>
        {loading ? (
          <div className="orbit-chat__context-value">Loading…</div>
        ) : projects.length === 0 ? (
          <div className="orbit-chat__context-value">No active projects</div>
        ) : (
          <ul className="orbit-chat__context-list">
            {projects.slice(0, 6).map((project) => (
              <li key={project.id}>
                <button
                  type="button"
                  className="orbit-chat__context-link"
                  onClick={() => onOpenProject(project.id)}
                >
                  {project.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="orbit-chat__context-section">
        <div className="orbit-chat__context-heading">Tasks</div>
        {loading ? (
          <div className="orbit-chat__context-value">Loading…</div>
        ) : openTasks.length === 0 ? (
          <div className="orbit-chat__context-value">No open tasks</div>
        ) : (
          <>
            <div className="orbit-chat__context-value">
              {openTasks.length} open task{openTasks.length === 1 ? "" : "s"}
            </div>
            <ul className="orbit-chat__context-list">
              {openTasks.slice(0, MAX_TASK_ROWS).map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    className="orbit-chat__context-link"
                    onClick={() => onNavigate("/tasks")}
                  >
                    {task.title}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="orbit-chat__context-section">
        <div className="orbit-chat__context-heading">Calendar</div>
        <div className="orbit-chat__context-value">
          {loading
            ? "Loading…"
            : calendarConnected === true
              ? "Connected to Google Calendar"
              : calendarConnected === false
                ? "Not connected"
                : "Unavailable"}
        </div>
      </section>

      <section className="orbit-chat__context-section">
        <div className="orbit-chat__context-heading">Documents</div>
        {loading ? (
          <div className="orbit-chat__context-value">Loading…</div>
        ) : (
          <div className="orbit-chat__context-value">
            {documents.length} document{documents.length === 1 ? "" : "s"}
          </div>
        )}
      </section>
    </aside>
  );
}
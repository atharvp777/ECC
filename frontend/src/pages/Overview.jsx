import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getPlanningToday, getPlanningDay, updateTask } from "../api";
import { ArrowRight, CalendarDays } from "lucide-react";
import TaskRow from "../components/TaskRow";
import OrbitButton from "../components/ui/OrbitButton";
import OrbitSkeleton from "../components/ui/OrbitSkeleton";
import { formatMinutes, formatShortDate, formatTime } from "../utils/format";

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning.";
  if (hour < 18) return "Good afternoon.";
  return "Good evening.";
}

function buildInsight(planning) {
  const overdue = planning?.tasks?.overdue || [];
  const dueToday = planning?.tasks?.due_today || [];
  const workload = planning?.workload || {};
  const criticalOverdue = overdue.filter((t) => t.priority === "critical").length;
  const highOverdue = overdue.filter((t) => t.priority === "high").length;
  const criticalDueToday = dueToday.filter((t) => t.priority === "critical").length;
  const highDueToday = dueToday.filter((t) => t.priority === "high").length;

  const verb = (n) => (n === 1 ? "is" : "are");
  const noun = (n, singular) => `${n} ${n === 1 ? singular : `${singular}s`}`;

  if (criticalOverdue + highOverdue > 0) {
    const n = criticalOverdue + highOverdue;
    return `${noun(n, "critical or high-priority task")} ${verb(n)} overdue.`;
  }
  if (overdue.length > 0) {
    return `${noun(overdue.length, "task")} ${verb(overdue.length)} overdue.`;
  }
  if (criticalDueToday > 0) {
    return `${noun(criticalDueToday, "critical task")} ${verb(criticalDueToday)} due today.`;
  }
  if (highDueToday > 0) {
    return `${noun(highDueToday, "high-priority task")} ${verb(highDueToday)} due today.`;
  }
  if (dueToday.length > 0) {
    return `${noun(dueToday.length, "task")} ${verb(dueToday.length)} due today.`;
  }
  if ((workload.upcoming_count || 0) > 0) {
    const n = workload.upcoming_count;
    return `${noun(n, "task")} ${verb(n)} coming up this week.`;
  }
  return "You're clear for today.";
}

function buildContext(planning) {
  const workload = planning?.workload || {};
  const dueToday = workload.due_today_count || 0;
  const overdue = workload.overdue_count || 0;
  if (dueToday > 0) return `You have ${dueToday} ${dueToday === 1 ? "task" : "tasks"} due today.`;
  if (overdue > 0) return `You have ${overdue} ${overdue === 1 ? "task" : "tasks"} overdue.`;
  return null;
}

function SectionSkeleton({ rows = 3 }) {
  return (
    <div className="overview-skeleton__section" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <OrbitSkeleton key={i} width="100%" height={44} />
      ))}
    </div>
  );
}

function LoadSummary({ workload }) {
  const minutes = workload.estimated_minutes_today || 0;
  const metrics = [
    ["open", workload.total_open_tasks || 0],
    ["due today", workload.due_today_count || 0],
    ["overdue", workload.overdue_count || 0],
    ["upcoming", workload.upcoming_count || 0],
  ];
  return (
    <div className="overview-load">
      <div className="overview-load__metrics">
        {metrics.map(([label, value]) => (
          <div className="overview-metric" key={label}>
            <span className="overview-metric__value">{value}</span>
            <span className="overview-metric__label">{label}</span>
          </div>
        ))}
      </div>
      <div className="overview-load__estimate">
        {minutes > 0 ? (
          <>
            <span className="overview-load__time">{formatMinutes(minutes)}</span>
            <span className="overview-load__caption">estimated today</span>
          </>
        ) : (
          <span className="overview-load__caption">Nothing estimated for today.</span>
        )}
      </div>
    </div>
  );
}

function CalendarPreview({ calendar, onConnect }) {
  if (!calendar) {
    return <p className="overview-calendar-state">Calendar unavailable.</p>;
  }
  if (!calendar.connected) {
    return (
      <div className="overview-calendar-state">
        <p>Google Calendar isn't connected.</p>
        <OrbitButton size="sm" variant="secondary" onClick={onConnect}>
          <CalendarDays size={13} aria-hidden="true" /> Connect calendar
        </OrbitButton>
      </div>
    );
  }
  const events = calendar.events || [];
  const windows = calendar.free_windows || [];
  if (events.length === 0) {
    return <p className="overview-calendar-state">Calendar is clear.</p>;
  }

  const timeline = [
    ...events.map((e) => ({ start: e.start, end: e.end, kind: "event", label: e.title, allDay: e.all_day })),
    ...windows.map((w) => ({ start: w.start, end: w.end, kind: "free", label: "Free" })),
  ].sort((a, b) => new Date(a.start) - new Date(b.start));

  return (
    <ul className="overview-timeline">
      {timeline.slice(0, 6).map((item, i) => (
        <li key={i} className="overview-timeline__item">
          <span className="overview-timeline__time">
            {item.allDay ? "All day" : `${formatTime(item.start)}–${formatTime(item.end)}`}
          </span>
          <span className={`overview-timeline__label ${item.kind === "free" ? "overview-timeline__label--free" : ""}`}>
            {item.label}
          </span>
        </li>
      ))}
    </ul>
  );
}

function DayPlanPanel({ plan, loading, error, onRetry }) {
  if (loading) return <SectionSkeleton rows={3} />;
  if (error) {
    return (
      <div className="overview-dayplan">
        <p className="overview-dayplan__note">Couldn't load the day plan.</p>
        <OrbitButton size="sm" variant="ghost" onClick={onRetry}>Retry</OrbitButton>
      </div>
    );
  }
  if (!plan) return null;

  const summary = plan.summary || {};
  const blocks = plan.scheduled_blocks || [];
  const unscheduled = plan.unscheduled_tasks || [];
  const planned = formatMinutes(summary.total_scheduled_minutes);

  return (
    <div className="overview-dayplan">
      <div className="overview-dayplan__summary">
        {summary.total_tasks > 0 ? (
          <>
            <span>{summary.scheduled_tasks} of {summary.total_tasks} tasks scheduled</span>
            {planned && (
              <>
                <span aria-hidden="true">·</span>
                <span>{planned} planned</span>
              </>
            )}
            {!plan.calendar_connected && (
              <span className="overview-dayplan__note">Connect Google Calendar to schedule these blocks.</span>
            )}
          </>
        ) : (
          <span>Nothing to plan for today.</span>
        )}
      </div>
      {blocks.length > 0 && (
        <ul className="overview-dayplan__blocks">
          {blocks.map((block, i) => (
            <li key={i}>
              <span className="overview-dayplan__time">{formatTime(block.start)}–{formatTime(block.end)}</span>
              <span className="overview-dayplan__title">{block.title}</span>
              {block.project && <span className="overview-dayplan__project">{block.project}</span>}
            </li>
          ))}
        </ul>
      )}
      {unscheduled.length > 0 && (
        <div className="overview-dayplan__unscheduled">
          <p className="overview-dayplan__unscheduled-title">Not scheduled</p>
          <ul>
            {unscheduled.map((task, i) => (
              <li key={i}>
                <span>{task.title}</span>
                <span className="overview-dayplan__reason">{task.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function Overview() {
  const navigate = useNavigate();
  const [planning, setPlanning] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [actionError, setActionError] = useState(null);

  const [dayPlanOpen, setDayPlanOpen] = useState(false);
  const [dayPlan, setDayPlan] = useState(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState(false);

  const load = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setPlanning(await getPlanningToday());
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleComplete = async (task) => {
    const taskId = task.id ?? task.task_id;
    const newStatus = task.status === "done" ? "todo" : "done";
    setActionError(null);
    try {
      await updateTask(taskId, { status: newStatus });
      load();
    } catch (error) {
      setActionError(`Couldn't ${newStatus === "done" ? "complete" : "reopen"} "${task.title}".`);
    }
  };

  const loadDayPlan = async () => {
    setPlanLoading(true);
    setPlanError(false);
    try {
      setDayPlan(await getPlanningDay());
    } catch {
      setPlanError(true);
    } finally {
      setPlanLoading(false);
    }
  };

  const toggleDayPlan = () => {
    if (dayPlanOpen) {
      setDayPlanOpen(false);
      return;
    }
    setDayPlanOpen(true);
    if (!dayPlan && !planLoading && !planError) loadDayPlan();
  };

  const insight = planning ? buildInsight(planning) : null;
  const contextLine = planning ? buildContext(planning) : null;
  const focus = planning?.focus_candidates || [];
  const workload = planning?.workload || {};
  const calendar = planning?.calendar;
  const upcoming = planning?.tasks?.upcoming || [];
  const deadlines = planning?.projects?.deadlines || [];
  const firstLoad = loading && !planning;

  return (
    <div className="page">
      <header className="overview-header">
        <h2>{greeting()}</h2>
        {contextLine && <p className="overview-header__context">{contextLine}</p>}
        <p className="overview-header__date">
          {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        </p>
      </header>

      {loadError && (
        <div className="overview-error" role="alert">
          <p>Couldn't load today's planning data.</p>
          <OrbitButton size="sm" variant="secondary" onClick={load}>Retry</OrbitButton>
        </div>
      )}

      {!loadError && (
        <div className="overview-grid">
          <div className="overview-primary">
            <div className="orbit-insight">
              <span className="orbit-insight__mark" aria-hidden="true">✦</span>
              {firstLoad ? <OrbitSkeleton width={240} height={14} shape="text" /> : <p>{insight}</p>}
            </div>

            <section className="overview-section" aria-labelledby="focus-heading">
              <h3 id="focus-heading">Today's Focus</h3>
              {firstLoad ? (
                <SectionSkeleton rows={3} />
              ) : focus.length === 0 ? (
                <div className="overview-empty">
                  <p className="overview-empty__title">You're clear for today.</p>
                  <p className="overview-empty__desc">No urgent or due-today work.</p>
                  <OrbitButton size="sm" variant="secondary" onClick={() => navigate("/chat")}>Ask Orbit</OrbitButton>
                </div>
              ) : (
                <div className="task-list">
                  {focus.slice(0, 5).map((c) => (
                    <TaskRow key={c.task_id} task={c} onComplete={handleComplete} onOpen={() => navigate("/tasks")} />
                  ))}
                </div>
              )}
              {actionError && <p className="overview-action-error" role="alert">{actionError}</p>}
            </section>

            <section className="overview-section" aria-labelledby="plan-heading">
              <h3 id="plan-heading">Plan My Day</h3>
              <OrbitButton variant="secondary" onClick={toggleDayPlan} aria-expanded={dayPlanOpen}>
                <span className="overview-plan-btn__mark" aria-hidden="true">✦</span>
                Plan my day
              </OrbitButton>
              {dayPlanOpen && (
                <DayPlanPanel plan={dayPlan} loading={planLoading} error={planError} onRetry={loadDayPlan} />
              )}
            </section>
          </div>

          <div className="overview-secondary">
            <section className="overview-section" aria-labelledby="load-heading">
              <h3 id="load-heading">Today's Load</h3>
              {firstLoad ? <SectionSkeleton rows={2} /> : <LoadSummary workload={workload} />}
            </section>

            <section className="overview-section" aria-labelledby="calendar-heading">
              <h3 id="calendar-heading">Calendar</h3>
              {firstLoad ? <SectionSkeleton rows={2} /> : <CalendarPreview calendar={calendar} onConnect={() => navigate("/integrations")} />}
            </section>

            <section className="overview-section" aria-labelledby="upcoming-heading">
              <div className="overview-section__header">
                <h3 id="upcoming-heading">Upcoming</h3>
                <button type="button" className="overview-section__link" onClick={() => navigate("/tasks")}>
                  View all tasks <ArrowRight size={12} aria-hidden="true" />
                </button>
              </div>
              {firstLoad ? (
                <SectionSkeleton rows={2} />
              ) : upcoming.length === 0 ? (
                <p className="overview-calendar-state">Nothing coming up in the next week.</p>
              ) : (
                <div className="task-list">
                  {upcoming.slice(0, 5).map((t) => (
                    <TaskRow key={t.task_id} task={t} onComplete={handleComplete} onOpen={() => navigate("/tasks")} />
                  ))}
                </div>
              )}
            </section>

            {!firstLoad && deadlines.length > 0 && (
              <section className="overview-section" aria-labelledby="deadlines-heading">
                <h3 id="deadlines-heading">Project Deadlines</h3>
                <ul className="overview-deadlines">
                  {deadlines.map((p) => (
                    <li key={p.project_id} className="overview-deadline">
                      <div className="overview-deadline__row">
                        <span className="overview-deadline__name">{p.name}</span>
                        <span className="overview-deadline__date">{formatShortDate(p.deadline)}</span>
                      </div>
                      <div className="progress-bar" role="presentation">
                        <div className="progress-fill" style={{ width: `${Math.round(p.progress * 100)}%`, background: "var(--accent)" }} />
                      </div>
                      <span className="overview-deadline__progress">{Math.round(p.progress * 100)}% complete</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
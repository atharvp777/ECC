import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getDashboardStats, getTodayTasks, getUpcomingTasks, updateTask } from "../api";
import { Check, AlertTriangle, Clock, Folder, CheckSquare, Zap } from "lucide-react";

function StatCard({ label, value, color, icon: Icon }) {
  return (
    <div className="stat-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <span className="label">{label}</span>
        {Icon && <Icon size={14} color={color || "var(--muted)"} />}
      </div>
      <div className="value" style={{ color: color || "var(--text)" }}>{value}</div>
      <div className="accent-bar" style={{ background: color || "var(--accent)" }} />
    </div>
  );
}

function TaskRow({ task, onDone }) {
  const overdue = task.deadline && new Date(task.deadline) < new Date() && task.status !== "done";
  const deadline = task.deadline ? new Date(task.deadline).toLocaleDateString() : null;

  return (
    <div className="task-item">
      <button
        className={`task-check ${task.status === "done" ? "done" : ""}`}
        onClick={() => onDone(task)}
      >
        {task.status === "done" && <Check size={10} />}
      </button>
      <div className="task-body">
        <div className={`task-title ${task.status === "done" ? "done" : ""}`}>{task.title}</div>
        <div className="task-meta">
          <span className={`badge badge-${task.priority}`}>{task.priority}</span>
          {deadline && <span className={overdue ? "overdue" : ""}>{overdue ? "⚠ " : ""}{deadline}</span>}
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats]       = useState(null);
  const [today, setToday]       = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [actionError, setActionError] = useState(null);
  const navigate = useNavigate();

  const load = async () => {
  try {
    const [s, t, u] = await Promise.all([
      getDashboardStats(),
      getTodayTasks(),
      getUpcomingTasks(7),
    ]);

    setStats(s);
    setToday(Array.isArray(t) ? t : []);
    setUpcoming(Array.isArray(u) ? u : []);
  } catch (error) {
    console.error("Dashboard API error:", error);
  } finally {
    setLoading(false);
  }
};

  useEffect(() => {
    load();
    const interval = setInterval(load, 4000);
    return () => clearInterval(interval);
  }, []);

  const handleDone = async (task) => {
    const newStatus = task.status === "done" ? "todo" : "done";
    setActionError(null);
    try {
      await updateTask(task.id, { status: newStatus });
      load();
    } catch (error) {
      console.error("Dashboard task update failed:", error);
      setActionError(
        `Couldn't ${newStatus === "done" ? "complete" : "reopen"} "${task.title}". Check the backend connection and try again.`
      );
    }
  };

  if (loading) return <div className="spinner" />;

  const now = new Date();
  const greeting = now.getHours() < 12 ? "Good morning" : now.getHours() < 18 ? "Good afternoon" : "Good evening";

  return (
    <div className="page">
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700 }}>{greeting}, Atharv 👋</h2>
        <p style={{ color: "var(--muted)", marginTop: 4 }}>
          {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        </p>
      </div>

      {/* Stats */}
      <div className="stats-grid">
        <StatCard label="Active Projects" value={stats?.active_projects ?? "—"} color="var(--accent)"  icon={Folder} />
        <StatCard label="Due Today"       value={stats?.due_today ?? "—"}       color="var(--warning)" icon={Clock} />
        <StatCard label="Overdue"         value={stats?.overdue_tasks ?? "—"}   color="var(--danger)"  icon={AlertTriangle} />
        <StatCard label="Critical"        value={stats?.critical_tasks ?? "—"}  color="var(--critical)"icon={Zap} />
        <StatCard label="Total Tasks"     value={stats?.total_tasks ?? "—"}     icon={CheckSquare} />
        <StatCard label="Completed"       value={stats?.done_tasks ?? "—"}      color="var(--success)" icon={Check} />
      </div>

      <div className="grid-2">
        {/* Today's tasks */}
        <div className="card">
          <div className="section-header">
            <h3>Today's Focus</h3>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate("/tasks")}>View all</button>
          </div>
          {today.length === 0
            ? <div className="empty"><p>Nothing due today 🎉</p></div>
            : <div className="task-list">{today.slice(0,6).map(t => <TaskRow key={t.id} task={t} onDone={handleDone} />)}</div>
          }
        </div>

        {/* Upcoming */}
        <div className="card">
          <div className="section-header">
            <h3>Coming up (7 days)</h3>
          </div>
          {upcoming.length === 0
            ? <div className="empty"><p>Clear runway ahead ✈</p></div>
            : <div className="task-list">{upcoming.slice(0,6).map(t => <TaskRow key={t.id} task={t} onDone={handleDone} />)}</div>
          }
        </div>
      </div>

      {actionError && (
        <div
          className="card"
          style={{ marginTop: 16, borderColor: "var(--danger)" }}
        >
          <p style={{ color: "var(--danger)", fontSize: 13 }}>⚠ {actionError}</p>
        </div>
      )}

      {!stats && !loading && (
  <div
    className="card"
    style={{
      marginTop: 16,
      borderColor: "var(--warning)",
      textAlign: "center",
    }}
  >
    <p style={{ color: "var(--warning)", fontSize: 13 }}>
      ⚠ Unable to load dashboard data. Check the backend connection.
    </p>
  </div>
)}
    </div>
  );
}


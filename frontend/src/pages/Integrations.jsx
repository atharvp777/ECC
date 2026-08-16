import { useEffect, useState } from "react";
import {
  getIntegrationStatus, getGoogleEvents, disconnectGoogle,
  getGithubRepos, getGithubIssues, getGithubPRs, getGithubCommits,
} from "../api";
import { Calendar, GitBranch, Check, X, ExternalLink, GitPullRequest, AlertCircle, GitCommit, RefreshCw } from "lucide-react";

const BASE = "http://localhost:8000";

// ── Helpers ──────────────────────────────────────────────────────────────────
function StatusBadge({ ok }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
      background: ok ? "rgba(34,197,94,.15)" : "rgba(100,116,139,.12)",
      color: ok ? "var(--success)" : "var(--muted)",
    }}>
      {ok ? <Check size={10} /> : <X size={10} />}
      {ok ? "Connected" : "Not connected"}
    </span>
  );
}

function SectionCard({ icon: Icon, title, color, children }) {
  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: `${color}22`, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon size={16} color={color} />
        </div>
        <h3 style={{ fontSize: 15, fontWeight: 600 }}>{title}</h3>
      </div>
      {children}
    </div>
  );
}

// ── Google Calendar ────────────────────────────────────────────────────────
function GoogleCalendarSection({ connected, onRefresh }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!connected) return;
    setLoading(true);
    try {
      const r = await getGoogleEvents(14);
      setEvents(r.events || []);
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [connected]);

  const handleDisconnect = async () => {
    if (!confirm("Disconnect Google Calendar?")) return;
    await disconnectGoogle(); onRefresh();
  };

  const fmtDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <SectionCard icon={Calendar} title="Google Calendar" color="#4285f4">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <StatusBadge ok={connected} />
        {!connected ? (
          <a href={`${BASE}/integrations/google/auth`} target="_blank" rel="noreferrer"
            className="btn btn-primary btn-sm">
            Connect Google Calendar
          </a>
        ) : (
          <>
            <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}><RefreshCw size={12} /></button>
            <button className="btn btn-danger btn-sm" onClick={handleDisconnect}>Disconnect</button>
          </>
        )}
      </div>

      {!connected && (
        <div style={{ background: "var(--surface2)", borderRadius: 10, padding: 16, fontSize: 13 }}>
          <p style={{ color: "var(--muted)", marginBottom: 12 }}>To connect Google Calendar:</p>
          <ol style={{ paddingLeft: 18, color: "var(--muted)", lineHeight: 2, fontSize: 12 }}>
            <li>Go to <strong style={{ color: "var(--text)" }}>console.cloud.google.com</strong></li>
            <li>Create a project → Enable <strong style={{ color: "var(--text)" }}>Google Calendar API</strong></li>
            <li>Create OAuth 2.0 credentials (Web application type)</li>
            <li>Add <code style={{ background: "var(--border)", padding: "0 4px", borderRadius: 3 }}>http://localhost:8000/integrations/google/callback</code> as redirect URI</li>
            <li>Copy Client ID & Client Secret → add to <code style={{ background: "var(--border)", padding: "0 4px", borderRadius: 3 }}>.env</code></li>
            <li>Restart backend → click Connect above</li>
          </ol>
        </div>
      )}

      {connected && (
        loading ? <div className="spinner" /> : (
          events.length === 0
            ? <p style={{ color: "var(--muted)", fontSize: 13 }}>No events in the next 14 days.</p>
            : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {events.map(e => (
                  <div key={e.id} style={{
                    background: "var(--surface2)", borderRadius: 8, padding: "10px 14px",
                    display: "flex", alignItems: "flex-start", gap: 12, border: "1px solid var(--border)",
                  }}>
                    <div style={{ width: 3, borderRadius: 2, alignSelf: "stretch", background: "#4285f4", flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 500, fontSize: 13 }}>{e.title}</div>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{fmtDate(e.start)}</div>
                      {e.location && <div style={{ fontSize: 11, color: "var(--muted)" }}>📍 {e.location}</div>}
                    </div>
                    {e.html_link && (
                      <a href={e.html_link} target="_blank" rel="noreferrer" style={{ color: "var(--muted)" }}>
                        <ExternalLink size={12} />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )
        )
      )}
    </SectionCard>
  );
}

// ── GitHub ────────────────────────────────────────────────────────────────
function GitHubSection({ connected }) {
  const [repos, setRepos]     = useState([]);
  const [selected, setSelected] = useState("");
  const [tab, setTab]         = useState("issues");   // issues | prs | commits
  const [data, setData]       = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!connected) return;
    getGithubRepos().then(r => {
      setRepos(r.repos || []);
      if (r.repos?.length) setSelected(r.repos[0].full_name);
    }).catch(() => {});
  }, [connected]);

  useEffect(() => {
    if (!selected) return;
    setLoading(true); setData([]);
    const loaders = { issues: getGithubIssues, prs: getGithubPRs, commits: getGithubCommits };
    loaders[tab](selected).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [selected, tab]);

  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString() : "";

  return (
    <SectionCard icon={GitBranch} title="GitHub" color="#e2e8f0">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <StatusBadge ok={connected} />
        {!connected && (
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            Add <code style={{ background: "var(--surface2)", padding: "0 4px", borderRadius: 3 }}>GITHUB_PAT=ghp_...</code> and <code style={{ background: "var(--surface2)", padding: "0 4px", borderRadius: 3 }}>GITHUB_USERNAME=yourname</code> to your <code style={{ background: "var(--surface2)", padding: "0 4px", borderRadius: 3 }}>.env</code>, then restart the backend.
          </span>
        )}
      </div>

      {connected && (
        <>
          {/* Repo selector */}
          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
            <select className="form-select" style={{ flex: 1, maxWidth: 320 }} value={selected} onChange={e => setSelected(e.target.value)}>
              {repos.map(r => <option key={r.full_name} value={r.full_name}>{r.full_name}</option>)}
            </select>
            {["issues", "prs", "commits"].map(t => (
              <button key={t} className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab(t)}>
                {t === "issues" ? <><AlertCircle size={12} /> Issues</> : t === "prs" ? <><GitPullRequest size={12} /> PRs</> : <><GitCommit size={12} /> Commits</>}
              </button>
            ))}
          </div>

          {loading ? <div className="spinner" /> : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {data.length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>Nothing here.</p>}
              {data.map((item, i) => (
                <div key={i} style={{
                  background: "var(--surface2)", border: "1px solid var(--border)",
                  borderRadius: 8, padding: "9px 12px",
                  display: "flex", alignItems: "flex-start", gap: 10,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {tab === "commits" ? item.message : `#${item.number} ${item.title}`}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, display: "flex", gap: 8 }}>
                      {tab === "commits" && <span>{item.sha} · {item.author} · {fmtDate(item.date)}</span>}
                      {tab === "issues" && <>{item.labels.map(l => <span key={l} className="tag">{l}</span>)} <span>{fmtDate(item.updated)}</span></>}
                      {tab === "prs" && <><span>{item.head} → {item.base}</span> {item.draft && <span className="badge badge-todo">draft</span>} <span>{fmtDate(item.updated)}</span></>}
                    </div>
                  </div>
                  <a href={item.url || item.html_url} target="_blank" rel="noreferrer" style={{ color: "var(--muted)", flexShrink: 0 }}>
                    <ExternalLink size={12} />
                  </a>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {connected && (
        <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)", fontSize: 12, color: "var(--muted)" }}>
          💡 To push a task to GitHub, go to <strong style={{ color: "var(--text)" }}>Tasks</strong>, hover a task, and click the GitHub icon.
        </div>
      )}
    </SectionCard>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────
export default function Integrations() {
  const [status, setStatus] = useState(null);

  const load = async () => {
    try { setStatus(await getIntegrationStatus()); } catch {}
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>Integrations</h2>
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>Connect external tools to your Command Center.</p>
      </div>
      <GoogleCalendarSection connected={!!status?.google_calendar} onRefresh={load} />
      <GitHubSection connected={!!status?.github} />
    </div>
  );
}


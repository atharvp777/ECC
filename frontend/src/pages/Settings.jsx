import { useEffect, useState } from "react";

export default function Settings() {
  const [aiStatus, setAiStatus] = useState(null);

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/chat/status")
      .then((r) => (r.ok ? r.json() : null))
      .then(setAiStatus)
      .catch(() => setAiStatus(null));
  }, []);

  return (
    <div className="page">
      <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 24 }}>Settings</h2>
      <div className="card" style={{ maxWidth: 480 }}>
        <div className="form-group">
          <label className="form-label">Backend URL</label>
          <input className="form-input" defaultValue="http://127.0.0.1:8000" disabled />
          <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 7 }}>
            The desktop app connects to this local service. Provider keys remain in the backend .env file and are never entered in the UI.
          </p>
        </div>
        <p style={{ color: "var(--muted)", fontSize: 12 }}>
          {aiStatus
            ? `AI provider: ${aiStatus.provider} — ${aiStatus.model}. Connection status is shown in the title bar.`
            : "AI provider status unavailable. Is the backend running?"}
        </p>
      </div>
    </div>
  );
}


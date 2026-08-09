export default function Settings() {
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
          AI provider: Groq. Connection status is shown in the title bar.
        </p>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { getBackendHealth } from "../../api/client";

const STATUS_TEXT = {
  checking: "Checking backend…",
  connected: "Backend connected",
  offline: "Backend unavailable",
};

export default function Topbar({ title }) {
  const [backendState, setBackendState] = useState("checking");

  useEffect(() => {
    let active = true;
    const checkHealth = async () => {
      try {
        await getBackendHealth();
        if (active) setBackendState("connected");
      } catch {
        if (active) setBackendState("offline");
      }
    };
    checkHealth();
    const interval = window.setInterval(checkHealth, 3000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const statusText = STATUS_TEXT[backendState];

  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
      <div className="topbar__status" role="status" aria-live="polite">
        <span className={`status-dot ${backendState}`} aria-hidden="true" />
        <span className="topbar__status-text">{statusText}</span>
      </div>
    </header>
  );
}

import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect, useState } from "react";
import { getBackendHealth } from "./api/client";
import Sidebar       from "./components/Sidebar";
import Dashboard     from "./pages/Dashboard";
import Projects      from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Tasks         from "./pages/Tasks";
import Notes         from "./pages/Notes";
import Documents     from "./pages/Documents";
import Chat          from "./pages/Chat";
import Integrations  from "./pages/Integrations";
import Settings      from "./pages/Settings";

function Topbar({ title }) {
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

  const statusText = {
    checking: "Checking backend…",
    connected: "Backend connected",
    offline: "Backend unavailable",
  }[backendState];

  return (
    <div className="topbar">
      <h2>{title}</h2>
      <div className={`status-dot ${backendState}`} title={statusText} aria-label={statusText} />
    </div>
  );
}

function Layout({ page, title }) {
  return (
    <>
      <Topbar title={title} />
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {page}
      </div>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Sidebar />
      <div className="main">
        <Routes>
          <Route path="/"             element={<Layout page={<Dashboard />}    title="Dashboard" />} />
          <Route path="/projects"     element={<Layout page={<Projects />}     title="Projects" />} />
          <Route path="/projects/:id" element={<Layout page={<ProjectDetail />} title="Project" />} />
          <Route path="/tasks"        element={<Layout page={<Tasks />}        title="Tasks" />} />
          <Route path="/notes"        element={<Layout page={<Notes />}        title="Notes" />} />
          <Route path="/documents"    element={<Layout page={<Documents />}    title="Knowledge Base" />} />
          <Route path="/chat"         element={<Layout page={<Chat />}         title="AI Chat" />} />
          <Route path="/integrations" element={<Layout page={<Integrations />} title="Integrations" />} />
          <Route path="/settings"     element={<Layout page={<Settings />}     title="Settings" />} />
          <Route path="*"             element={<Layout page={<Dashboard />}    title="Dashboard" />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

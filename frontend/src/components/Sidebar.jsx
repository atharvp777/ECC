import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, FolderKanban, CheckSquare,
  FileText, FileArchive, Users, Settings, Zap, MessageSquare, Plug,
} from "lucide-react";

const NAV = [
  { label: "Main", items: [
    { icon: LayoutDashboard, title: "Dashboard",  path: "/" },
    { icon: FolderKanban,   title: "Projects",   path: "/projects" },
    { icon: CheckSquare,    title: "Tasks",      path: "/tasks" },
  ]},
  { label: "Knowledge", items: [
    { icon: FileText,       title: "Notes",      path: "/notes" },
    { icon: FileArchive,    title: "Documents",  path: "/documents" },
    { icon: Users,          title: "Meetings",   path: "/meetings" },
  ]},
  { label: "AI", items: [
    { icon: MessageSquare,  title: "AI Chat",    path: "/chat" },
  ]},
  { label: "System", items: [
    { icon: Plug,     title: "Integrations", path: "/integrations" },
    { icon: Settings, title: "Settings",     path: "/settings" },
  ]},
];

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();

  const [backendDetected, setBackendDetected] = useState(false);
  useEffect(() => {
    const checkBackend = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/', {
          method: 'GET',
        });
        setBackendDetected(response.ok);
      } catch {
        setBackendDetected(false);
      }
    };
    checkBackend();
  }, []);

  if (!backendDetected) {
    return (
      <div className="sidebar-notice">
        Backend not detected. Run start.bat in the backend folder to connect.
      </div>
    );
  }

  return (
    <nav className="sidebar">
      <div className="sidebar-logo">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Zap size={16} color="var(--accent)" />
          <h1>Command Center</h1>
        </div>
      </div>

      {NAV.map(group => (
        <div className="nav-group" key={group.label}>
          <div className="nav-label">{group.label}</div>
          {group.items.map(item => {
            const active = location.pathname === item.path ||
              (item.path !== "/" && location.pathname.startsWith(item.path));
            return (
              <button
                key={item.path}
                className={`nav-item ${active ? "active" : ""}`}
                onClick={() => navigate(item.path)}
              >
                <item.icon size={16} />
                {item.title}
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

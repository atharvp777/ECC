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

  return (
    <nav className="sidebar">
      <div className="sidebar-logo">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Zap size={16} color="var(--accent)" />
          <h1>Command Center</h1>
        </div>
        <p>Atharv · Pegasus Racing</p>
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

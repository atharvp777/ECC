import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, ListChecks, CalendarDays, FolderKanban, Files,
  Sparkles, Settings, Search, PanelLeftClose, PanelLeftOpen,
  CalendarCheck, CalendarX, AlertTriangle, Folder,
} from "lucide-react";
import { getProjects, getIntegrationStatus } from "../../api";

const PRIMARY_NAV = [
  { icon: LayoutDashboard, label: "Overview", path: "/", end: true },
  { icon: ListChecks, label: "Tasks", path: "/tasks" },
  { icon: CalendarDays, label: "Calendar", path: "/calendar" },
];

const WORK_NAV = [
  { icon: FolderKanban, label: "Projects", path: "/projects" },
  { icon: Files, label: "Documents", path: "/documents" },
];

const COLLAPSE_STORAGE_KEY = "orbit.sidebar.collapsed";

function NavItem({ icon: Icon, label, path, end, collapsed, className = "" }) {
  return (
    <NavLink
      to={path}
      end={end}
      aria-label={label}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        `sidebar__link ${className} ${isActive ? "sidebar__link--active" : ""}`.trim()
      }
    >
      <Icon size={16} className="sidebar__link-icon" aria-hidden="true" />
      {!collapsed && <span className="sidebar__link-text">{label}</span>}
    </NavLink>
  );
}

function RecentProjects({ collapsed }) {
  const [projects, setProjects] = useState(null);

  useEffect(() => {
    let active = true;
    getProjects()
      .then((list) => {
        if (active) setProjects(Array.isArray(list) ? list.slice(0, 3) : []);
      })
      .catch(() => {
        if (active) setProjects([]);
      });
    return () => {
      active = false;
    };
  }, []);

  if (collapsed || !projects || projects.length < 3) return null;

  return (
    <div className="sidebar__group sidebar__recent">
      <div className="sidebar__label">Recent Projects</div>
      {projects.map((project) => (
        <NavLink
          key={project.id}
          to={`/projects/${project.id}`}
          aria-label={`Open project ${project.name}`}
          title={project.name}
          className={({ isActive }) =>
            `sidebar__link sidebar__link--recent ${isActive ? "sidebar__link--active" : ""}`.trim()
          }
        >
          <Folder size={14} className="sidebar__link-icon" aria-hidden="true" />
          <span className="sidebar__link-text">{project.name}</span>
        </NavLink>
      ))}
    </div>
  );
}

const GOOGLE_STATUS = {
  checking: { text: "Checking…", tone: "warn", icon: CalendarX },
  connected: { text: "Connected", tone: "ok", icon: CalendarCheck },
  readonly: { text: "Read only", tone: "warn", icon: AlertTriangle },
  disconnected: { text: "Not connected", tone: "off", icon: CalendarX },
  unknown: { text: "Unavailable", tone: "off", icon: CalendarX },
};

function GoogleStatus({ collapsed }) {
  const [state, setState] = useState("checking");

  useEffect(() => {
    let active = true;
    getIntegrationStatus()
      .then((status) => {
        if (!active) return;
        if (status && status.google_calendar) {
          setState(status.google_calendar_can_write ? "connected" : "readonly");
        } else {
          setState("disconnected");
        }
      })
      .catch(() => {
        if (active) setState("unknown");
      });
    return () => {
      active = false;
    };
  }, []);

  const { text, tone, icon: Icon } = GOOGLE_STATUS[state];

  return (
    <NavLink
      to="/integrations"
      aria-label={`Google Calendar status — ${text}`}
      title={collapsed ? text : undefined}
      className={({ isActive }) =>
        `sidebar__link sidebar__link--status ${isActive ? "sidebar__link--active" : ""}`.trim()
      }
    >
      <Icon size={16} className="sidebar__link-icon" aria-hidden="true" />
      {!collapsed && (
        <>
          <span className="sidebar__link-text">Google Calendar</span>
          <span className={`sidebar__status sidebar__status--${tone}`}>{text}</span>
        </>
      )}
    </NavLink>
  );
}

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export default function Sidebar({ onSearch = () => {} }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setCollapsed((current) => {
          const next = !current;
          try {
            localStorage.setItem(COLLAPSE_STORAGE_KEY, next ? "1" : "0");
          } catch {}
          return next;
        });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const toggleCollapse = () => {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem(COLLAPSE_STORAGE_KEY, next ? "1" : "0");
      } catch {}
      return next;
    });
  };

  return (
    <nav className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`} aria-label="Primary">
      <div className="sidebar__brand">
        <span className="sidebar__mark" aria-hidden="true">✦</span>
        {!collapsed && <span className="sidebar__name">Orbit</span>}
      </div>

      <div className="sidebar__body">
        <button type="button" className="sidebar__search" aria-label="Search" onClick={onSearch}>
          <Search size={15} className="sidebar__search-icon" aria-hidden="true" />
          {!collapsed && (
            <>
              <span className="sidebar__search-text">Search…</span>
              <kbd className="sidebar__kbd">⌘K</kbd>
            </>
          )}
        </button>

        <div className="sidebar__group">
          {PRIMARY_NAV.map((item) => (
            <NavItem
              key={item.path}
              icon={item.icon}
              label={item.label}
              path={item.path}
              end={item.end}
              collapsed={collapsed}
            />
          ))}
        </div>

        <div className="sidebar__group">
          <div className="sidebar__label">Work</div>
          {WORK_NAV.map((item) => (
            <NavItem
              key={item.path}
              icon={item.icon}
              label={item.label}
              path={item.path}
              collapsed={collapsed}
            />
          ))}
        </div>

        <RecentProjects collapsed={collapsed} />

        <div className="sidebar__group">
          <NavItem
            icon={Sparkles}
            label="Orbit AI"
            path="/chat"
            collapsed={collapsed}
            className="sidebar__link--ai"
          />
        </div>
      </div>

      <div className="sidebar__footer">
        <GoogleStatus collapsed={collapsed} />
        <NavItem
          icon={Settings}
          label="Settings"
          path="/settings"
          collapsed={collapsed}
        />
        <button
          type="button"
          className="sidebar__collapse"
          onClick={toggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeftOpen size={16} aria-hidden="true" />
          ) : (
            <PanelLeftClose size={16} aria-hidden="true" />
          )}
          {!collapsed && <span className="sidebar__collapse-text">Collapse</span>}
        </button>
      </div>
    </nav>
  );
}

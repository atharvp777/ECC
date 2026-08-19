import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import { getProject } from "../../api";

const ROUTE_TITLES = {
  "/": "Overview",
  "/tasks": "Tasks",
  "/calendar": "Calendar",
  "/projects": "Projects",
  "/documents": "Documents",
  "/chat": "Orbit AI",
  "/settings": "Settings",
  "/integrations": "Integrations",
  "/notes": "Notes",
};

const PROJECT_DETAIL_RE = /^\/projects\/(\d+)$/;

function usePageTitle() {
  const location = useLocation();
  const [title, setTitle] = useState(
    () => ROUTE_TITLES[location.pathname] || "Overview"
  );

  useEffect(() => {
    const match = location.pathname.match(PROJECT_DETAIL_RE);
    if (!match) {
      setTitle(ROUTE_TITLES[location.pathname] || "Overview");
      return;
    }
    let active = true;
    setTitle("Projects");
    getProject(match[1])
      .then((project) => {
        if (active && project && project.name) setTitle(project.name);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [location.pathname]);

  return title;
}

export default function AppShell({ children }) {
  const title = usePageTitle();
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main">
        <Topbar title={title} />
        <div className="main__content">{children}</div>
      </div>
    </div>
  );
}

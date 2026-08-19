import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Sidebar from "./Sidebar";

vi.mock("../../api", () => ({
  getProjects: vi.fn(),
  getIntegrationStatus: vi.fn(),
}));

import { getProjects, getIntegrationStatus } from "../../api";

const projects = [
  { id: 1, name: "BAJA HV", category: "baja", status: "ACTIVE", task_count: 5, done_tasks: 2 },
  { id: 2, name: "In-SEM", category: "college", status: "ACTIVE", task_count: 0, done_tasks: 0 },
  { id: 3, name: "dMAT", category: "rover", status: "ACTIVE", task_count: 3, done_tasks: 3 },
  { id: 4, name: "Fourth", category: "other", status: "ACTIVE", task_count: 0, done_tasks: 0 },
];

function renderSidebar(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="*" element={<Sidebar />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderWithRoutes(initialRoute, routes) {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>{routes}</Routes>
    </MemoryRouter>
  );
}

async function flushSidebar() {
  await waitFor(() => expect(getProjects).toHaveBeenCalled());
  await waitFor(() => expect(getIntegrationStatus).toHaveBeenCalled());
}

beforeEach(() => {
  localStorage.clear();
  getProjects.mockResolvedValue(projects);
  getIntegrationStatus.mockResolvedValue({ google_calendar: true, google_calendar_can_write: true });
});

describe("Sidebar", () => {
  it("renders brand, primary nav, work nav, Orbit AI, and Settings", async () => {
    renderSidebar();
    await flushSidebar();
    expect(screen.getByText("✦")).toBeInTheDocument();
    expect(screen.getByText("Orbit")).toBeInTheDocument();
    for (const label of ["Overview", "Tasks", "Calendar", "Work", "Projects", "Documents", "Orbit AI", "Settings", "Google Calendar", "Collapse"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("marks the active route with aria-current", async () => {
    renderSidebar("/projects");
    await flushSidebar();
    const projectsLink = screen.getByRole("link", { name: "Projects" });
    expect(projectsLink).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Tasks" })).not.toHaveAttribute("aria-current");
  });

  it("does not mark Overview active for non-root paths", async () => {
    renderSidebar("/projects");
    await flushSidebar();
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("renders recent projects capped at 3", async () => {
    renderSidebar();
    expect(await screen.findByText("Recent Projects")).toBeInTheDocument();
    await flushSidebar();
    expect(screen.getByText("BAJA HV")).toBeInTheDocument();
    expect(screen.getByText("In-SEM")).toBeInTheDocument();
    expect(screen.getByText("dMAT")).toBeInTheDocument();
    expect(screen.queryByText("Fourth")).not.toBeInTheDocument();
  });

  it("hides recent projects when there are fewer than 3", async () => {
    getProjects.mockResolvedValue(projects.slice(0, 2));
    renderSidebar();
    await flushSidebar();
    expect(screen.queryByText("Recent Projects")).not.toBeInTheDocument();
  });

  it("keeps nav visible when backend calls fail", async () => {
    getProjects.mockRejectedValue(new Error("down"));
    getIntegrationStatus.mockRejectedValue(new Error("down"));
    renderSidebar();
    await flushSidebar();
    expect(screen.getByRole("link", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByText("Backend not detected")).not.toBeInTheDocument();
  });

  it("navigates to the calendar route", async () => {
    renderWithRoutes("/", [
      <Route key="home" path="/" element={<Sidebar />} />,
      <Route key="cal" path="/calendar" element={<div>CALENDAR PAGE</div>} />,
    ]);
    await flushSidebar();
    fireEvent.click(screen.getByRole("link", { name: "Calendar" }));
    expect(screen.getByText("CALENDAR PAGE")).toBeInTheDocument();
  });

  it("navigates to a recent project detail", async () => {
    renderWithRoutes("/", [
      <Route key="home" path="/" element={<Sidebar />} />,
      <Route key="proj" path="/projects/:id" element={<div>PROJECT PAGE</div>} />,
    ]);
    const projectLink = await screen.findByRole("link", { name: "Open project BAJA HV" });
    await flushSidebar();
    fireEvent.click(projectLink);
    expect(screen.getByText("PROJECT PAGE")).toBeInTheDocument();
  });

  it("navigates to settings", async () => {
    renderWithRoutes("/", [
      <Route key="home" path="/" element={<Sidebar />} />,
      <Route key="settings" path="/settings" element={<div>SETTINGS PAGE</div>} />,
    ]);
    await flushSidebar();
    fireEvent.click(screen.getByRole("link", { name: "Settings" }));
    expect(screen.getByText("SETTINGS PAGE")).toBeInTheDocument();
  });

  it("navigates to integrations from the Google status row", async () => {
    renderWithRoutes("/", [
      <Route key="home" path="/" element={<Sidebar />} />,
      <Route key="integrations" path="/integrations" element={<div>INTEGRATIONS PAGE</div>} />,
    ]);
    const googleLink = await screen.findByRole("link", { name: "Google Calendar status — Connected" });
    fireEvent.click(googleLink);
    expect(screen.getByText("INTEGRATIONS PAGE")).toBeInTheDocument();
  });

  it("toggles collapse via the button and persists to localStorage", async () => {
    const { container } = renderSidebar();
    await flushSidebar();
    expect(container.querySelector(".sidebar")).not.toHaveClass("sidebar--collapsed");

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(container.querySelector(".sidebar")).toHaveClass("sidebar--collapsed");
    expect(localStorage.getItem("orbit.sidebar.collapsed")).toBe("1");
    expect(screen.queryByText("Tasks")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(container.querySelector(".sidebar")).not.toHaveClass("sidebar--collapsed");
    expect(localStorage.getItem("orbit.sidebar.collapsed")).toBe("0");
  });

  it("toggles collapse with Ctrl+B", async () => {
    const { container } = renderSidebar();
    await flushSidebar();
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(container.querySelector(".sidebar")).toHaveClass("sidebar--collapsed");
    fireEvent.keyDown(window, { key: "B", ctrlKey: true });
    expect(container.querySelector(".sidebar")).not.toHaveClass("sidebar--collapsed");
  });

  it("toggles collapse with Cmd+B", async () => {
    const { container } = renderSidebar();
    await flushSidebar();
    fireEvent.keyDown(window, { key: "b", metaKey: true });
    expect(container.querySelector(".sidebar")).toHaveClass("sidebar--collapsed");
  });

  it("restores collapsed state from localStorage on mount", async () => {
    localStorage.setItem("orbit.sidebar.collapsed", "1");
    const { container } = renderSidebar();
    await flushSidebar();
    expect(container.querySelector(".sidebar")).toHaveClass("sidebar--collapsed");
  });

  it("shows connected Google status when connected and writable", async () => {
    renderSidebar();
    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Google Calendar status — Connected" })).toBeInTheDocument();
  });

  it("shows read-only Google status when connected without write", async () => {
    getIntegrationStatus.mockResolvedValue({ google_calendar: true, google_calendar_can_write: false });
    renderSidebar();
    expect(await screen.findByText("Read only")).toBeInTheDocument();
  });

  it("shows disconnected Google status when not connected", async () => {
    getIntegrationStatus.mockResolvedValue({ google_calendar: false, google_calendar_can_write: false });
    renderSidebar();
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
  });

  it("shows unavailable Google status when the status request fails", async () => {
    getIntegrationStatus.mockRejectedValue(new Error("down"));
    renderSidebar();
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  });

  it("shows the ⌘K search hint in the expanded state", async () => {
    renderSidebar();
    await flushSidebar();
    expect(screen.getByText("⌘K")).toBeInTheDocument();
    const search = screen.getByRole("button", { name: "Search" });
    expect(within(search).getByText("Search…")).toBeInTheDocument();
  });

  it("calls onSearch when the search button is clicked", async () => {
    const onSearch = vi.fn();
    renderWithRoutes("/", [
      <Route key="home" path="*" element={<Sidebar onSearch={onSearch} />} />,
    ]);
    await flushSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch).toHaveBeenCalled();
  });
});
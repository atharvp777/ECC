import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import AppShell from "./AppShell";

vi.mock("../../api", () => ({
  getProject: vi.fn(),
  getProjects: vi.fn(),
  getIntegrationStatus: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  getBackendHealth: vi.fn(),
}));

import { getProject, getProjects, getIntegrationStatus } from "../../api";
import { getBackendHealth } from "../../api/client";

const projects = [
  { id: 1, name: "BAJA HV", category: "baja", status: "ACTIVE", task_count: 5, done_tasks: 2 },
  { id: 2, name: "In-SEM", category: "college", status: "ACTIVE", task_count: 0, done_tasks: 0 },
  { id: 3, name: "dMAT", category: "rover", status: "ACTIVE", task_count: 3, done_tasks: 3 },
];

function renderAppShell(route, content) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="*" element={<AppShell>{content}</AppShell>} />
      </Routes>
    </MemoryRouter>
  );
}

async function flushAppShell() {
  await waitFor(() => expect(getProjects).toHaveBeenCalled());
  await waitFor(() => expect(getIntegrationStatus).toHaveBeenCalled());
  await waitFor(() => expect(getBackendHealth).toHaveBeenCalled());
}

function bannerTitle() {
  const banner = screen.getByRole("banner");
  return within(banner).getByRole("heading", { level: 1 });
}

beforeEach(() => {
  localStorage.clear();
  getProjects.mockResolvedValue(projects);
  getIntegrationStatus.mockResolvedValue({ google_calendar: true, google_calendar_can_write: true });
  getBackendHealth.mockResolvedValue({ status: "ok" });
  getProject.mockResolvedValue({ id: 1, name: "BAJA HV" });
});

describe("AppShell", () => {
  it("shows the Overview title on the root route", async () => {
    renderAppShell("/", <div>CONTENT</div>);
    await flushAppShell();
    expect(bannerTitle()).toHaveTextContent("Overview");
  });

  it("shows centralized titles for each static route", async () => {
    const cases = [
      ["/tasks", "Tasks"],
      ["/calendar", "Calendar"],
      ["/projects", "Projects"],
      ["/documents", "Documents"],
      ["/chat", "Orbit AI"],
      ["/settings", "Settings"],
      ["/integrations", "Integrations"],
      ["/notes", "Notes"],
    ];
    for (const [route, title] of cases) {
      const { unmount } = renderAppShell(route, <div>CONTENT</div>);
      await flushAppShell();
      expect(bannerTitle()).toHaveTextContent(title);
      unmount();
    }
  });

  it("shows the project name for a project detail route", async () => {
    renderAppShell("/projects/1", <div>CONTENT</div>);
    await waitFor(() => expect(bannerTitle()).toHaveTextContent("BAJA HV"));
    await flushAppShell();
  });

  it("falls back to Projects when the project cannot be loaded", async () => {
    getProject.mockRejectedValue(new Error("down"));
    renderAppShell("/projects/1", <div>CONTENT</div>);
    await waitFor(() => expect(bannerTitle()).toHaveTextContent("Projects"));
    await flushAppShell();
  });

  it("renders the page content inside the main content area", async () => {
    renderAppShell("/", <div>CONTENT AREA</div>);
    await flushAppShell();
    expect(screen.getByText("CONTENT AREA")).toBeInTheDocument();
  });

  it("reports a connected backend in the topbar", async () => {
    renderAppShell("/", <div>CONTENT</div>);
    await waitFor(() => {
      expect(screen.getByText("Backend connected")).toBeInTheDocument();
    });
    await flushAppShell();
  });

  it("reports an unavailable backend in the topbar", async () => {
    getBackendHealth.mockRejectedValue(new Error("down"));
    renderAppShell("/", <div>CONTENT</div>);
    await waitFor(() => {
      expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
    });
    await flushAppShell();
  });
});
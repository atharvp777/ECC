import { describe, it, expect, vi } from "vitest";

vi.mock("../api", () => ({
  getDashboardStats: vi.fn().mockResolvedValue({
    active_projects: 3,
    due_today: 2,
    overdue_tasks: 1,
    critical_tasks: 0,
    total_tasks: 10,
    done_tasks: 4,
  }),
  getTodayTasks: vi.fn().mockResolvedValue([]),
  getUpcomingTasks: vi.fn().mockResolvedValue([]),
  updateTask: vi.fn(),
}));

import { screen, waitFor } from "@testing-library/react";
import Dashboard from "../pages/Dashboard";
import { renderWithRouter } from "../test/renderWithRouter";

describe("Dashboard", () => {
  it("renders stats from the backend", async () => {
    renderWithRouter(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("3")).toBeInTheDocument();
    });
    expect(screen.getByText("Active Projects")).toBeInTheDocument();
    expect(screen.getByText("Today's Focus")).toBeInTheDocument();
  });
});
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Overview from "./Overview";

vi.mock("../api", () => ({
  getPlanningToday: vi.fn(),
  getPlanningDay: vi.fn(),
  updateTask: vi.fn(),
}));

import { getPlanningToday, getPlanningDay, updateTask } from "../api";

function at(hour, minute = 0, dayOffset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

function makePlanning(overrides = {}) {
  return {
    generated_at: new Date().toISOString(),
    timezone: "IST",
    tasks: {
      overdue: [
        { task_id: 11, title: "Overdue battery report", priority: "high", status: "todo", deadline: at(10, 0, -1), estimated_minutes: 60, project_id: 2, project_name: "BAJA HV" },
      ],
      due_today: [
        { task_id: 12, title: "Submit lab manual", priority: "medium", status: "todo", deadline: at(23, 59, 0), estimated_minutes: 60, project_id: 1, project_name: "In-SEM" },
      ],
      upcoming: [
        { task_id: 13, title: "HCI Unit 2", priority: "medium", status: "todo", deadline: at(9, 0, 3), estimated_minutes: 90, project_id: 1, project_name: "In-SEM" },
        { task_id: 14, title: "Battery validation", priority: "high", status: "todo", deadline: at(9, 0, 4), estimated_minutes: 120, project_id: 2, project_name: "BAJA HV" },
      ],
      critical: [],
    },
    focus_candidates: [
      { task_id: 12, title: "Submit lab manual", priority: "medium", deadline: at(23, 59, 0), estimated_minutes: 45, project_id: 1, project_name: "In-SEM", reasons: ["due_today"] },
      { task_id: 11, title: "Overdue battery report", priority: "high", deadline: at(10, 0, -1), estimated_minutes: 60, project_id: 2, project_name: "BAJA HV", reasons: ["overdue", "high"] },
    ],
    projects: {
      deadlines: [
        { project_id: 1, name: "In-SEM", deadline: at(0, 0, 5), status: "ACTIVE", total_tasks: 25, done_tasks: 17, progress: 0.68 },
      ],
    },
    workload: { total_open_tasks: 7, overdue_count: 1, due_today_count: 2, upcoming_count: 3, critical_count: 1, estimated_minutes_today: 195 },
    calendar: {
      connected: true,
      events: [
        { title: "Team meeting", start: at(9, 0, 0), end: at(10, 0, 0), all_day: false, location: null },
      ],
      free_windows: [
        { start: at(10, 0, 0), end: at(13, 0, 0), duration_minutes: 180 },
      ],
    },
    ...overrides,
  };
}

function renderOverview(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/tasks" element={<div>TASKS PAGE</div>} />
        <Route path="/chat" element={<div>CHAT PAGE</div>} />
        <Route path="/integrations" element={<div>INTEGRATIONS PAGE</div>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getPlanningToday.mockResolvedValue(makePlanning());
  getPlanningDay.mockResolvedValue({
    date: "2026-08-19",
    timezone: "IST",
    generated_at: new Date().toISOString(),
    scheduled_blocks: [
      { task_id: 12, title: "Submit lab manual", project: "In-SEM", start: at(10, 0, 0), end: at(10, 45, 0), duration_minutes: 45, reasons: [] },
    ],
    unscheduled_tasks: [
      { task_id: 11, title: "Overdue battery report", estimated_minutes: 60, priority: "high", deadline: at(10, 0, -1), reason: "Too long to fit remaining free time" },
    ],
    unused_windows: [],
    summary: { total_tasks: 2, scheduled_tasks: 1, unscheduled_tasks: 1, total_scheduled_minutes: 45, total_available_minutes: 300, unused_minutes: 0, calendar_connected: false },
  });
  updateTask.mockResolvedValue({});
});

describe("Overview", () => {
  it("renders the page shell and section headings", async () => {
    renderOverview();
    expect(screen.getByText(/Good (morning|afternoon|evening)\./)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Today's Focus" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Today's Load" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Calendar" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Plan My Day" })).toBeInTheDocument();
  });

  it("loads planning data on mount and shows a contextual line", async () => {
    renderOverview();
    expect(await screen.findByText("Submit lab manual")).toBeInTheDocument();
    expect(getPlanningToday).toHaveBeenCalledTimes(1);
    expect(screen.getByText("You have 2 tasks due today.")).toBeInTheDocument();
  });

  it("renders focus candidates", async () => {
    renderOverview();
    expect(await screen.findByText("Submit lab manual")).toBeInTheDocument();
    expect(screen.getByText("Overdue battery report")).toBeInTheDocument();
  });

  it("renders focus candidate metadata", async () => {
    renderOverview();
    const row = (await screen.findByText("Submit lab manual")).closest(".task-item");
    expect(within(row).getByText("In-SEM")).toBeInTheDocument();
    expect(within(row).getByText("medium")).toBeInTheDocument();
    expect(within(row).getByText("Due today")).toBeInTheDocument();
    expect(within(row).getByText("45m")).toBeInTheDocument();

    const overdueRow = screen.getByText("Overdue battery report").closest(".task-item");
    expect(within(overdueRow).getByText("Overdue")).toBeInTheDocument();
    expect(within(overdueRow).getByText("1h")).toBeInTheDocument();
  });

  it("shows a deterministic insight from planning signals", async () => {
    renderOverview();
    expect(await screen.findByText("1 critical or high-priority task is overdue.")).toBeInTheDocument();
  });

  it("shows a clear-day insight when nothing needs attention", async () => {
    const empty = makePlanning({
      tasks: { overdue: [], due_today: [], upcoming: [], critical: [] },
      focus_candidates: [],
      workload: { total_open_tasks: 0, overdue_count: 0, due_today_count: 0, upcoming_count: 0, critical_count: 0, estimated_minutes_today: 0 },
    });
    getPlanningToday.mockResolvedValue(empty);
    renderOverview();
    const messages = await screen.findAllByText("You're clear for today.");
    expect(messages.length).toBeGreaterThan(0);
  });

  it("shows the focus empty state with an Ask Orbit action", async () => {
    getPlanningToday.mockResolvedValue(makePlanning({ focus_candidates: [] }));
    renderOverview();
    expect(await screen.findByText("No urgent or due-today work.")).toBeInTheDocument();
    expect(screen.getByText("You're clear for today.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask Orbit" })).toBeInTheDocument();
  });

  it("shows the workload summary", async () => {
    renderOverview();
    const loadSection = (await screen.findByRole("heading", { name: "Today's Load" })).closest("section");
    expect(within(loadSection).getByText("7")).toBeInTheDocument();
    expect(within(loadSection).getByText("open")).toBeInTheDocument();
    expect(within(loadSection).getByText("2")).toBeInTheDocument();
    expect(within(loadSection).getByText("due today")).toBeInTheDocument();
    expect(within(loadSection).getByText("1")).toBeInTheDocument();
    expect(within(loadSection).getByText("overdue")).toBeInTheDocument();
    expect(within(loadSection).getByText("3")).toBeInTheDocument();
    expect(within(loadSection).getByText("upcoming")).toBeInTheDocument();
  });

  it("formats estimated time naturally", async () => {
    renderOverview();
    const loadSection = (await screen.findByRole("heading", { name: "Today's Load" })).closest("section");
    expect(within(loadSection).getByText("3h 15m")).toBeInTheDocument();
    expect(within(loadSection).getByText("estimated today")).toBeInTheDocument();
  });

  it("shows 'Nothing estimated for today' when workload is zero", async () => {
    const zero = makePlanning();
    zero.workload = { ...zero.workload, estimated_minutes_today: 0 };
    getPlanningToday.mockResolvedValue(zero);
    renderOverview();
    const loadSection = (await screen.findByRole("heading", { name: "Today's Load" })).closest("section");
    expect(within(loadSection).getByText("Nothing estimated for today.")).toBeInTheDocument();
  });

  it("shows today's calendar events and free windows when connected", async () => {
    renderOverview();
    expect(await screen.findByText("Team meeting")).toBeInTheDocument();
    expect(screen.getByText("Free")).toBeInTheDocument();
    expect(screen.getByText("09:00–10:00")).toBeInTheDocument();
  });

  it("shows a clear calendar when connected with no events", async () => {
    getPlanningToday.mockResolvedValue(
      makePlanning({ calendar: { connected: true, events: [], free_windows: [] } })
    );
    renderOverview();
    expect(await screen.findByText("Calendar is clear.")).toBeInTheDocument();
  });

  it("shows the disconnected calendar state and connects via integrations", async () => {
    getPlanningToday.mockResolvedValue(
      makePlanning({ calendar: { connected: false, events: [], free_windows: [] } })
    );
    renderOverview();
    expect(await screen.findByText("Google Calendar isn't connected.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect calendar" }));
    expect(screen.getByText("INTEGRATIONS PAGE")).toBeInTheDocument();
  });

  it("renders upcoming tasks", async () => {
    renderOverview();
    expect(await screen.findByText("HCI Unit 2")).toBeInTheDocument();
    expect(screen.getByText("Battery validation")).toBeInTheDocument();
  });

  it("renders project deadlines when present", async () => {
    renderOverview();
    const deadlinesSection = (await screen.findByRole("heading", { name: "Project Deadlines" })).closest("section");
    expect(within(deadlinesSection).getByText("In-SEM")).toBeInTheDocument();
    expect(within(deadlinesSection).getByText("68% complete")).toBeInTheDocument();
  });

  it("does not render project deadlines when none exist", async () => {
    getPlanningToday.mockResolvedValue(makePlanning({ projects: { deadlines: [] } }));
    renderOverview();
    await screen.findByText("Submit lab manual");
    expect(screen.queryByRole("heading", { name: "Project Deadlines" })).not.toBeInTheDocument();
  });

  it("shows a planning error with a working Retry", async () => {
    getPlanningToday.mockRejectedValueOnce(new Error("down"));
    renderOverview();
    expect(await screen.findByText("Couldn't load today's planning data.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByText(/Good (morning|afternoon|evening)\./)).toBeInTheDocument();

    getPlanningToday.mockResolvedValueOnce(makePlanning());
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Submit lab manual")).toBeInTheDocument();
  });

  it("keeps the page rendered when the backend is down", async () => {
    getPlanningToday.mockRejectedValue(new Error("down"));
    renderOverview();
    expect(await screen.findByText("Couldn't load today's planning data.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("Today's Focus")).not.toBeInTheDocument();
  });

  it("navigates to chat from Ask Orbit", async () => {
    getPlanningToday.mockResolvedValue(makePlanning({ focus_candidates: [] }));
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "Ask Orbit" }));
    expect(screen.getByText("CHAT PAGE")).toBeInTheDocument();
  });

  it("navigates to tasks from View all tasks", async () => {
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: /View all tasks/ }));
    expect(screen.getByText("TASKS PAGE")).toBeInTheDocument();
  });

  it("opens the tasks page when a focus row is clicked or activated", async () => {
    renderOverview();
    const row = await screen.findByText("Submit lab manual");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(screen.getByText("TASKS PAGE")).toBeInTheDocument();
  });

  it("completes a focus task through the checkbox", async () => {
    renderOverview();
    const completeButton = await screen.findByRole("button", { name: "Complete Submit lab manual" });
    fireEvent.click(completeButton);
    await waitFor(() => expect(updateTask).toHaveBeenCalledWith(12, { status: "done" }));
  });

  it("loads and displays the read-only day plan", async () => {
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "Plan my day" }));
    expect(getPlanningDay).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("1 of 2 tasks scheduled")).toBeInTheDocument();
    const panel = document.querySelector(".overview-dayplan");
    expect(within(panel).getByText("Submit lab manual")).toBeInTheDocument();
    expect(within(panel).getByText("Not scheduled")).toBeInTheDocument();
    expect(within(panel).getByText("Overdue battery report")).toBeInTheDocument();
  });

  it("shows a day plan error with retry", async () => {
    getPlanningDay.mockRejectedValueOnce(new Error("down"));
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "Plan my day" }));
    expect(await screen.findByText("Couldn't load the day plan.")).toBeInTheDocument();
    getPlanningDay.mockResolvedValueOnce({
      date: "2026-08-19",
      timezone: "IST",
      generated_at: new Date().toISOString(),
      scheduled_blocks: [],
      unscheduled_tasks: [],
      unused_windows: [],
      summary: { total_tasks: 0, scheduled_tasks: 0, unscheduled_tasks: 0, total_scheduled_minutes: 0, total_available_minutes: 0, unused_minutes: 0, calendar_connected: false },
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Nothing to plan for today.")).toBeInTheDocument();
  });
});
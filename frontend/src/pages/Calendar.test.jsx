import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Calendar from "./Calendar";

vi.mock("../api", () => ({
  getIntegrationStatus: vi.fn(),
  getGoogleEvents: vi.fn(),
  getTasks: vi.fn(),
  getProjects: vi.fn(),
  getPlanningDay: vi.fn(),
  unlinkTaskFromCalendar: vi.fn(),
  linkTaskToCalendar: vi.fn(),
}));

import {
  getIntegrationStatus,
  getGoogleEvents,
  getTasks,
  getProjects,
  getPlanningDay,
  unlinkTaskFromCalendar,
  linkTaskToCalendar,
} from "../api";
import { formatWeekRange } from "../utils/calendar";

function at(hour, minute = 0, dayOffset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

function dateOnly(dayOffset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function makeStatus(overrides = {}) {
  return {
    google_calendar: true,
    google_calendar_connected: true,
    google_calendar_can_write: true,
    ...overrides,
  };
}

function makeGoogleEvents() {
  return [
    { id: "g1", title: "Team meeting", start: at(9, 0, 0), end: at(10, 0, 0), all_day: false, location: "Room 5", description: "Weekly sync", html_link: "https://calendar.google.com/event/g1" },
    { id: "g2", title: "All-day review", start: dateOnly(0), end: dateOnly(1), all_day: true, location: null, description: null, html_link: null },
  ];
}

function makeTasks() {
  return [
    { id: 1, title: "Submit lab manual", priority: "medium", status: "todo", project_id: 1, deadline: at(23, 59, 0), estimated_minutes: 45, scheduled_start: at(10, 0, 0), scheduled_end: at(10, 45, 0), google_calendar_event_id: "evt-orbit-1", calendar_sync_error: null },
    { id: 2, title: "Overdue battery report", priority: "high", status: "todo", project_id: 2, deadline: at(10, 0, -1), estimated_minutes: 60, scheduled_start: null, scheduled_end: null, google_calendar_event_id: null },
    { id: 3, title: "Finished item", priority: "low", status: "done", project_id: null, deadline: at(9, 0, -2), estimated_minutes: 30, scheduled_start: null, scheduled_end: null, google_calendar_event_id: null },
  ];
}

function makeProjects() {
  return [
    { id: 1, name: "In-SEM" },
    { id: 2, name: "BAJA HV" },
  ];
}

function makePlan() {
  return {
    date: "2026-08-19",
    timezone: "IST",
    generated_at: new Date().toISOString(),
    scheduled_blocks: [
      { task_id: 1, title: "Submit lab manual", project: "In-SEM", start: at(10, 0, 0), end: at(10, 45, 0), duration_minutes: 45, reasons: ["due_today"] },
    ],
    unscheduled_tasks: [
      { task_id: 2, title: "Overdue battery report", estimated_minutes: 60, priority: "high", deadline: at(10, 0, -1), reason: "insufficient_remaining_time" },
    ],
    unused_windows: [
      { start: at(11, 0, 0), end: at(13, 0, 0), duration_minutes: 120 },
    ],
    summary: { total_tasks: 2, scheduled_tasks: 1, unscheduled_tasks: 1, total_scheduled_minutes: 45, total_available_minutes: 120, unused_minutes: 120, calendar_connected: true },
  };
}

function renderCalendar(route = "/calendar") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/calendar" element={<Calendar />} />
        <Route path="/chat" element={<div>CHAT PAGE</div>} />
        <Route path="/tasks" element={<div>TASKS PAGE</div>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  getIntegrationStatus.mockResolvedValue(makeStatus());
  getGoogleEvents.mockResolvedValue({ connected: true, events: makeGoogleEvents() });
  getTasks.mockResolvedValue(makeTasks());
  getProjects.mockResolvedValue(makeProjects());
  getPlanningDay.mockResolvedValue(makePlan());
  unlinkTaskFromCalendar.mockResolvedValue({});
  linkTaskToCalendar.mockResolvedValue({});
});

describe("Calendar", () => {
  it("renders the page shell", async () => {
    renderCalendar();
    expect(screen.getByRole("heading", { name: "Calendar" })).toBeInTheDocument();
    expect(screen.getByText("Your schedule, tasks, and available time.")).toBeInTheDocument();
  });

  it("shows a skeleton while initial data is loading", () => {
    getIntegrationStatus.mockReturnValue(new Promise(() => {}));
    renderCalendar();
    expect(document.querySelector(".calendar-skeleton")).toBeInTheDocument();
  });

  it("defaults to the week view with Monday through Sunday columns", async () => {
    renderCalendar();
    await screen.findByText("Team meeting");
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((day) => {
      expect(screen.getByText(day)).toBeInTheDocument();
    });
  });

  it("renders Google events, all-day events, orbit tasks, and deadlines", async () => {
    renderCalendar();
    const meeting = await screen.findByRole("button", { name: /Team meeting/ });
    expect(meeting.classList.contains("calendar-event--google")).toBe(true);

    expect(screen.getByRole("button", { name: /All-day review/ })).toBeInTheDocument();

    const orbitBtn = screen.getByRole("button", { name: /Submit lab manual, 10:00/ });
    expect(orbitBtn.classList.contains("calendar-event--orbit")).toBe(true);

    const deadlineBtn = screen.getByRole("button", { name: /Overdue battery report/ });
    expect(deadlineBtn.classList.contains("calendar-event--deadline")).toBe(true);
    expect(deadlineBtn.classList.contains("calendar-event--overdue")).toBe(true);

    expect(screen.queryByRole("button", { name: /Finished item/ })).not.toBeInTheDocument();
  });

  it("does not duplicate a Google event already linked to an orbit task", async () => {
    getGoogleEvents.mockResolvedValue({
      connected: true,
      events: [
        { id: "evt-orbit-1", title: "Submit lab manual (Google copy)", start: at(10, 0, 0), end: at(10, 45, 0), all_day: false, location: null, description: null, html_link: null },
      ],
    });
    renderCalendar();
    await screen.findByRole("button", { name: /Submit lab manual, 10:00/ });
    expect(screen.queryByRole("button", { name: /Google copy/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Submit lab manual, 10:00/ })).toHaveLength(1);
  });

  it("shows the connected state", async () => {
    renderCalendar();
    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Syncing with Google Calendar")).toBeInTheDocument();
  });

  it("shows the not-connected state with a connect action", async () => {
    getIntegrationStatus.mockResolvedValue(makeStatus({ google_calendar: false, google_calendar_can_write: false }));
    getGoogleEvents.mockResolvedValue({ connected: false, events: [] });
    renderCalendar();
    expect(await screen.findByText("Connect Google Calendar to see your schedule here.")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Connect Google Calendar" });
    expect(link.getAttribute("href")).toContain("/integrations/google/auth");
  });

  it("shows the read-only state", async () => {
    getIntegrationStatus.mockResolvedValue(makeStatus({ google_calendar_can_write: false }));
    renderCalendar();
    expect(await screen.findByText("Read-only calendar access — reconnect to write events.")).toBeInTheDocument();
  });

  it("shows an error state with a working retry", async () => {
    getIntegrationStatus.mockRejectedValueOnce(new Error("down"));
    renderCalendar();
    expect(await screen.findByText("Calendar couldn't be loaded.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it("switches between week, day, and month views", async () => {
    renderCalendar();
    await screen.findByText("Team meeting");

    fireEvent.click(screen.getByRole("button", { name: "Day" }));
    expect(document.querySelector(".calendar-day-view")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Team meeting/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    expect(document.querySelector(".calendar-month")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Team meeting/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Mon" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Week" }));
    expect(document.querySelector(".calendar-grid")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Team meeting/ })).toBeInTheDocument();
  });

  it("navigates week by week and jumps back to today", async () => {
    renderCalendar();
    await screen.findByText("Team meeting");
    const range = () => document.querySelector(".calendar-toolbar__range").textContent;
    const before = range();

    fireEvent.click(screen.getByRole("button", { name: "Next week" }));
    await waitFor(() => expect(range()).not.toBe(before));

    fireEvent.click(screen.getByRole("button", { name: /Previous week/ }));
    await waitFor(() => expect(range()).toBe(before));

    fireEvent.click(screen.getByRole("button", { name: "Next week" }));
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(range()).toBe(formatWeekRange(new Date())));
  });

  it("reveals overflow events in the month view via +N more", async () => {
    const extra = [
      { id: "x1", title: "Extra one", start: at(11, 0, 0), end: at(12, 0, 0), all_day: false, location: null, description: null, html_link: null },
      { id: "x2", title: "Extra two", start: at(12, 0, 0), end: at(13, 0, 0), all_day: false, location: null, description: null, html_link: null },
      { id: "x3", title: "Extra three", start: at(13, 0, 0), end: at(14, 0, 0), all_day: false, location: null, description: null, html_link: null },
      { id: "x4", title: "Extra four", start: at(14, 0, 0), end: at(15, 0, 0), all_day: false, location: null, description: null, html_link: null },
    ];
    getGoogleEvents.mockResolvedValue({ connected: true, events: [...makeGoogleEvents(), ...extra] });
    renderCalendar();
    await screen.findByText("Team meeting");

    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    fireEvent.click(await screen.findByRole("button", { name: /more$/ }));
    expect(document.querySelector(".calendar-day-view")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Extra four/ })).toBeInTheDocument();
  });

  it("opens the event detail drawer for a Google event", async () => {
    renderCalendar();
    fireEvent.click(await screen.findByRole("button", { name: /Team meeting/ }));
    const dialog = screen.getByRole("dialog", { name: "Team meeting" });
    expect(within(dialog).getByText("Google Calendar event")).toBeInTheDocument();
    expect(within(dialog).getByText("Room 5")).toBeInTheDocument();
    expect(within(dialog).getByText("Weekly sync")).toBeInTheDocument();
    expect(within(dialog).getByText("09:00–10:00")).toBeInTheDocument();
    const openLink = screen.getByRole("link", { name: /Open in Google Calendar/ });
    expect(openLink.getAttribute("href")).toBe("https://calendar.google.com/event/g1");
  });

  it("opens the task drawer from an orbit task and opens the task page", async () => {
    renderCalendar();
    fireEvent.click(await screen.findByRole("button", { name: /Submit lab manual, 10:00/ }));
    const dialog = screen.getByRole("dialog", { name: "Submit lab manual" });
    expect(within(dialog).getByText("Scheduled task")).toBeInTheDocument();
    expect(within(dialog).getByText("In-SEM")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open task" }));
    expect(screen.getByText("TASKS PAGE")).toBeInTheDocument();
  });

  it("removes a task from the calendar", async () => {
    renderCalendar();
    fireEvent.click(await screen.findByRole("button", { name: /Submit lab manual, 10:00/ }));
    fireEvent.click(screen.getByRole("button", { name: /Remove from calendar/ }));
    await waitFor(() => expect(unlinkTaskFromCalendar).toHaveBeenCalledWith(1));
  });

  it("retries calendar sync for a linked task", async () => {
    renderCalendar();
    fireEvent.click(await screen.findByRole("button", { name: /Submit lab manual, 10:00/ }));
    fireEvent.click(screen.getByRole("button", { name: /Retry sync/ }));
    await waitFor(() =>
      expect(linkTaskToCalendar).toHaveBeenCalledWith(1, {
        scheduled_start: expect.any(String),
        scheduled_end: expect.any(String),
        duration_minutes: 60,
      })
    );
  });

  it("hides schedule actions when calendar access is read-only", async () => {
    getIntegrationStatus.mockResolvedValue(makeStatus({ google_calendar_can_write: false }));
    renderCalendar();
    fireEvent.click(await screen.findByRole("button", { name: /Submit lab manual, 10:00/ }));
    expect(screen.getByText("Read-only calendar access — reconnect Google Calendar to edit events.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove from calendar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry sync/ })).not.toBeInTheDocument();
  });

  it("opens the deadline detail drawer", async () => {
    renderCalendar();
    fireEvent.click(await screen.findByRole("button", { name: /Overdue battery report/ }));
    const dialog = screen.getByRole("dialog", { name: "Overdue battery report" });
    expect(within(dialog).getAllByText("Deadline").length).toBeGreaterThan(0);
    expect(within(dialog).getByText("BAJA HV")).toBeInTheDocument();
    expect(within(dialog).getByText("1 day overdue")).toBeInTheDocument();
  });

  it("loads and displays the day plan", async () => {
    renderCalendar();
    await screen.findByText("Team meeting");
    fireEvent.click(screen.getByRole("button", { name: "Plan My Day" }));
    expect(getPlanningDay).toHaveBeenCalledTimes(1);

    const dialog = await screen.findByRole("dialog", { name: "Plan My Day" });
    expect(within(dialog).getByText("1 of 2 tasks scheduled")).toBeInTheDocument();
    expect(within(dialog).getByText("45m planned")).toBeInTheDocument();
    expect(within(dialog).getByText("Submit lab manual")).toBeInTheDocument();
    expect(within(dialog).getByText("In-SEM")).toBeInTheDocument();
    expect(within(dialog).getByText("Available time")).toBeInTheDocument();
    expect(within(dialog).getByText("11:00–13:00")).toBeInTheDocument();
    expect(within(dialog).getByText("Not scheduled")).toBeInTheDocument();
    expect(within(dialog).getByText("Overdue battery report")).toBeInTheDocument();
    expect(within(dialog).getByText("Not enough remaining time")).toBeInTheDocument();
  });

  it("shows a day plan error with retry", async () => {
    getPlanningDay.mockRejectedValueOnce(new Error("down"));
    renderCalendar();
    await screen.findByText("Team meeting");
    fireEvent.click(screen.getByRole("button", { name: "Plan My Day" }));
    expect(await screen.findByText("Couldn't load today's plan.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("1 of 2 tasks scheduled")).toBeInTheDocument();
  });

  it("schedules the plan by navigating to chat with a prefilled message", async () => {
    renderCalendar();
    await screen.findByText("Team meeting");
    fireEvent.click(screen.getByRole("button", { name: "Plan My Day" }));
    fireEvent.click(await screen.findByRole("button", { name: /Schedule this plan with Orbit/ }));

    expect(await screen.findByText("CHAT PAGE")).toBeInTheDocument();
    const stored = JSON.parse(sessionStorage.getItem("ecc_chat_messages"));
    expect(stored.some((m) => m.role === "user" && /day plan/.test(m.content))).toBe(true);
  });

  it("surfaces a stale plan instead of silently scheduling stale data", async () => {
    renderCalendar();
    await screen.findByText("Team meeting");
    fireEvent.click(screen.getByRole("button", { name: "Plan My Day" }));
    await screen.findByRole("dialog", { name: "Plan My Day" });

    getPlanningDay.mockResolvedValueOnce({
      ...makePlan(),
      scheduled_blocks: [
        { task_id: 5, title: "Changed task", project: "In-SEM", start: at(10, 30, 0), end: at(11, 0, 0), duration_minutes: 30, reasons: ["due_today"] },
      ],
      summary: { ...makePlan().summary, total_tasks: 3 },
    });

    fireEvent.click(screen.getByRole("button", { name: /Schedule this plan with Orbit/ }));
    expect(await screen.findByText("Your plan has changed since it was created.")).toBeInTheDocument();
    expect(screen.queryByText("CHAT PAGE")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review updated plan" }));
    expect(screen.getByText("Changed task")).toBeInTheDocument();
  });

  it("closes the event drawer with Escape and restores focus", async () => {
    renderCalendar();
    const eventBtn = await screen.findByRole("button", { name: /Team meeting/ });
    fireEvent.click(eventBtn);
    expect(screen.getByRole("dialog", { name: "Team meeting" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(eventBtn);
  });

  it("refreshes the connection state when the window regains focus", async () => {
    renderCalendar();
    await screen.findByText("Connected");

    getIntegrationStatus.mockResolvedValue(makeStatus({ google_calendar: false, google_calendar_can_write: false }));
    fireEvent(window, new Event("focus"));
    expect(await screen.findByText("Connect Google Calendar to see your schedule here.")).toBeInTheDocument();
  });
});
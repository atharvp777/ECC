import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Tasks from "./Tasks";
import { renderWithRouter } from "../test/renderWithRouter";

vi.mock("../api", () => ({
  getTasks: vi.fn(),
  getProjects: vi.fn(),
  createTask: vi.fn(),
  updateTask: vi.fn(),
  deleteTask: vi.fn(),
  linkTaskToCalendar: vi.fn(),
  unlinkTaskFromCalendar: vi.fn(),
}));

import {
  getTasks,
  getProjects,
  createTask,
  updateTask,
  deleteTask,
  linkTaskToCalendar,
  unlinkTaskFromCalendar,
} from "../api";

const projects = [
  { id: 1, name: "BAJA HV" },
  { id: 2, name: "dMAT" },
  { id: 3, name: "In-SEM" },
];

// Deadlines are built relative to "now" so grouping is stable across runs.
const at = (dayOffset, hour, minute = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
};

const tasks = [
  { id: 1, title: "Finish HCI Unit 1", description: "Read chapter 3 and submit", priority: "high", status: "todo", task_type: "work", deadline: at(0, 23, 59), estimated_minutes: 45, project_id: 3 },
  { id: 2, title: "Review battery calcs", priority: "critical", status: "todo", task_type: "work", deadline: at(-2, 10, 0), estimated_minutes: 90, project_id: 1 },
  { id: 3, title: "Draft final report", priority: "medium", status: "todo", task_type: "work", deadline: at(3, 17, 0), estimated_minutes: 90, project_id: 2 },
  { id: 4, title: "Order parts", priority: "low", status: "todo", task_type: "reminder", deadline: null, estimated_minutes: null, project_id: null },
  { id: 5, title: "Submit invoice", priority: "medium", status: "done", task_type: "work", deadline: at(-1, 12, 0), estimated_minutes: 15, project_id: 2, completed_at: at(-1, 18, 0) },
  { id: 6, title: "Standup meeting", priority: "high", status: "in_progress", task_type: "meeting", deadline: at(1, 10, 0), estimated_minutes: 30, project_id: 1, google_calendar_event_id: "evt1", scheduled_start: at(1, 10, 0), scheduled_end: at(1, 10, 30) },
  { id: 7, title: "Battery report", priority: "high", status: "todo", task_type: "work", deadline: at(-1, 11, 0), estimated_minutes: 60, project_id: 1, google_calendar_event_id: "evt2", scheduled_start: at(0, 14, 0), scheduled_end: at(0, 15, 30), calendar_sync_error: "Google returned 401" },
];

function renderTasks() {
  return renderWithRouter(<Tasks />);
}

beforeEach(() => {
  vi.clearAllMocks();
  getTasks.mockResolvedValue(tasks);
  getProjects.mockResolvedValue(projects);
  createTask.mockResolvedValue({ id: 99 });
  updateTask.mockResolvedValue({});
  deleteTask.mockResolvedValue({});
  linkTaskToCalendar.mockResolvedValue({});
  unlinkTaskFromCalendar.mockResolvedValue({});
});

describe("Tasks workspace", () => {
  it("renders the workspace with groups and toolbar", async () => {
    renderTasks();
    expect(await screen.findByText("Finish HCI Unit 1")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Overdue" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "No deadline" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Completed" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search tasks...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New task" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Active" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter by priority" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter by project" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter by type" })).toBeInTheDocument();
  });

  it("puts tasks into the right groups", async () => {
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    expect(within(screen.getByRole("region", { name: "Today" })).getByText("Finish HCI Unit 1")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Overdue" })).getByText("Review battery calcs")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Overdue" })).getByText("Battery report")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Upcoming" })).getByText("Draft final report")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Upcoming" })).getByText("Standup meeting")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "No deadline" })).getByText("Order parts")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Completed" })).getByText("Submit invoice")).toBeInTheDocument();
  });

  it("labels overdue tasks with readable day counts", async () => {
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    const overdue = screen.getByRole("region", { name: "Overdue" });
    expect(within(overdue).getByText("2 days overdue")).toBeInTheDocument();
    expect(within(overdue).getByText("1 day overdue")).toBeInTheDocument();
  });

  it("searches by title, description, and project name", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    const search = screen.getByPlaceholderText("Search tasks...");

    await user.type(search, "report");
    expect(screen.getByText("Draft final report")).toBeInTheDocument();
    expect(screen.getByText("Battery report")).toBeInTheDocument();
    expect(screen.queryByText("Order parts")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "chapter");
    expect(screen.getByText("Finish HCI Unit 1")).toBeInTheDocument();
    expect(screen.queryByText("Order parts")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "baja");
    expect(screen.getByText("Review battery calcs")).toBeInTheDocument();
    expect(screen.queryByText("Order parts")).not.toBeInTheDocument();
  });

  it("filters by priority", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by priority" }), "high");
    expect(screen.getByText("Finish HCI Unit 1")).toBeInTheDocument();
    expect(screen.getByText("Standup meeting")).toBeInTheDocument();
    expect(screen.getByText("Battery report")).toBeInTheDocument();
    expect(screen.queryByText("Order parts")).not.toBeInTheDocument();
    expect(screen.queryByText("Draft final report")).not.toBeInTheDocument();
  });

  it("filters by project", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by project" }), "1");
    expect(screen.getByText("Review battery calcs")).toBeInTheDocument();
    expect(screen.getByText("Battery report")).toBeInTheDocument();
    expect(screen.getByText("Standup meeting")).toBeInTheDocument();
    expect(screen.queryByText("Finish HCI Unit 1")).not.toBeInTheDocument();
    expect(screen.queryByText("Order parts")).not.toBeInTheDocument();
  });

  it("filters by status via the segmented control", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");

    await user.click(screen.getByRole("button", { name: "Completed" }));
    expect(screen.getByText("Submit invoice")).toBeInTheDocument();
    expect(screen.queryByText("Finish HCI Unit 1")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Active" }));
    expect(screen.getByText("Finish HCI Unit 1")).toBeInTheDocument();
    expect(screen.queryByText("Submit invoice")).not.toBeInTheDocument();
  });

  it("filters by task type", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");

    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by type" }), "reminder");
    expect(screen.getByText("Order parts")).toBeInTheDocument();
    expect(screen.queryByText("Finish HCI Unit 1")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by type" }), "meeting");
    expect(screen.getByText("Standup meeting")).toBeInTheDocument();
    expect(screen.queryByText("Order parts")).not.toBeInTheDocument();
  });

  it("shows an empty search state and clears filters", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.type(screen.getByPlaceholderText("Search tasks..."), "zzz-not-found");
    expect(screen.getByText("No matching tasks.")).toBeInTheDocument();
    expect(screen.getByText("Try a different search or clear filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Finish HCI Unit 1")).toBeInTheDocument();
  });

  it("shows the no-tasks empty state", async () => {
    getTasks.mockResolvedValue([]);
    renderTasks();
    expect(await screen.findByText("No tasks yet.")).toBeInTheDocument();
    expect(screen.getByText("Create your first task.")).toBeInTheDocument();
    expect(
      within(screen.getByText("No tasks yet.").closest(".tasks-empty")).getByRole("button", { name: "New task" })
    ).toBeInTheDocument();
  });

  it("creates a task through the drawer", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.click(screen.getByRole("button", { name: "New task" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("New task")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Task Title *"), "New thermal test");
    await user.click(within(dialog).getByRole("button", { name: "Add Task" }));
    await waitFor(() => {
      expect(createTask).toHaveBeenCalledWith(
        expect.objectContaining({ title: "New thermal test", priority: "medium", status: "todo", project_id: null })
      );
    });
    expect(await screen.findByText("Task created")).toBeInTheDocument();
  });

  it("opens the drawer when a row is clicked and shows the list behind it", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.click(screen.getByText("Finish HCI Unit 1"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAccessibleName("Finish HCI Unit 1");
    expect(document.querySelector(".task-drawer")).toBeInTheDocument();
    expect(document.querySelector(".task-drawer-overlay")).toBeInTheDocument();
    // the underlying task list stays mounted, not a separate page
    expect(screen.getByRole("region", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search tasks...")).toBeInTheDocument();
  });

  it("renders drawer metadata fields", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.click(screen.getByText("Finish HCI Unit 1"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Todo")).toBeInTheDocument();
    expect(within(dialog).getByText("HIGH")).toBeInTheDocument();
    expect(within(dialog).getByText("In-SEM")).toBeInTheDocument();
    expect(within(dialog).getByText("Work")).toBeInTheDocument();
    expect(within(dialog).getByText("Due today")).toBeInTheDocument();
    expect(within(dialog).getByText("45m")).toBeInTheDocument();
    expect(within(dialog).getByText("Read chapter 3 and submit")).toBeInTheDocument();
  });

  it("edits a task without dropping the estimate to null", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.click(screen.getByText("Finish HCI Unit 1"));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Edit" }));

    const titleInput = screen.getByLabelText("Task Title *");
    expect(titleInput).toHaveValue("Finish HCI Unit 1");
    await user.clear(titleInput);
    await user.type(titleInput, "Finish HCI Unit 2");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ title: "Finish HCI Unit 2", estimated_minutes: 45 })
      );
    });
  });

  it("completes a task through its checkbox", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.click(screen.getByRole("button", { name: "Complete Finish HCI Unit 1" }));
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(1, { status: "done" });
    });
    expect(await screen.findByText("Task completed")).toBeInTheDocument();
  });

  it("reopens a completed task", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Submit invoice");
    await user.click(screen.getByRole("button", { name: "Reopen Submit invoice" }));
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(5, { status: "todo" });
    });
  });

  it("asks for confirmation before deleting", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Review battery calcs");
    await user.click(screen.getByRole("button", { name: "Delete Review battery calcs" }));
    await screen.findByText("Delete task?");
    const modal = document.querySelector(".modal");
    expect(within(modal).getByText('"Review battery calcs"')).toBeInTheDocument();
    expect(within(modal).getByText("This cannot be undone.")).toBeInTheDocument();
    expect(deleteTask).not.toHaveBeenCalled();
  });

  it("deletes a task after confirmation", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Review battery calcs");
    await user.click(screen.getByRole("button", { name: "Delete Review battery calcs" }));
    await screen.findByText("Delete task?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(deleteTask).toHaveBeenCalledWith(2);
    });
    expect(await screen.findByText("Task deleted")).toBeInTheDocument();
  });

  it("does not claim deletion success when the backend fails", async () => {
    const user = userEvent.setup();
    deleteTask.mockRejectedValueOnce(new Error("nope"));
    renderTasks();
    await screen.findByText("Review battery calcs");
    await user.click(screen.getByRole("button", { name: "Delete Review battery calcs" }));
    await screen.findByText("Delete task?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Couldn't delete task")).toBeInTheDocument();
    expect(deleteTask).toHaveBeenCalledWith(2);
  });

  it("formats estimates naturally and shows nothing when missing", async () => {
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    const reportRow = screen.getByText("Draft final report").closest(".task-item");
    expect(within(reportRow).getByText("1h 30m")).toBeInTheDocument();
    const hciRow = screen.getByText("Finish HCI Unit 1").closest(".task-item");
    expect(within(hciRow).getByText("45m")).toBeInTheDocument();

    const orderRow = screen.getByText("Order parts").closest(".task-item");
    expect(within(orderRow).queryByText(/m$/)).not.toBeInTheDocument();
  });

  it("shows the missing estimate as an em dash in the drawer", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Order parts");
    await user.click(screen.getByText("Order parts"));
    const dialog = await screen.findByRole("dialog");
    const estimateField = [...dialog.querySelectorAll(".task-drawer__field")].find(
      (f) => f.textContent.startsWith("Estimate")
    );
    expect(estimateField).toBeTruthy();
    expect(estimateField).toHaveTextContent("—");
    expect(estimateField).not.toHaveTextContent("45m");
  });

  it("shows a compact calendar indicator for linked tasks", async () => {
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    const row = screen.getByText("Standup meeting").closest(".task-item");
    expect(within(row).getByText(/^Scheduled/)).toBeInTheDocument();
  });

  it("warns about calendar sync errors without dumping the raw string in the list", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    const row = screen.getByText("Battery report").closest(".task-item");
    expect(within(row).getByText("Calendar sync issue")).toBeInTheDocument();
    expect(within(row).queryByText("Google returned 401")).not.toBeInTheDocument();

    await user.click(screen.getByText("Battery report"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Calendar sync issue")).toBeInTheDocument();
    expect(within(dialog).getByText("Google returned 401")).toBeInTheDocument();
  });

  it("opens the drawer with Enter and closes it with Escape, restoring focus", async () => {
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    const body = screen
      .getAllByRole("button", { name: /Finish HCI Unit 1/ })
      .find((b) => b.classList.contains("task-body"));
    expect(body).toBeTruthy();
    body.focus();
    fireEvent.keyDown(body, { key: "Enter" });
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toHaveFocus();
  });

  it("shows an error with a working retry when loading fails", async () => {
    const user = userEvent.setup();
    getTasks.mockRejectedValueOnce(new Error("down"));
    renderTasks();
    expect(await screen.findByText("Couldn't load your tasks.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Finish HCI Unit 1")).toBeInTheDocument();
  });

  it("keeps the underlying list visible while the drawer is open", async () => {
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText("Finish HCI Unit 1");
    await user.click(screen.getByText("Finish HCI Unit 1"));
    await screen.findByRole("dialog");
    expect(screen.getByText("Review battery calcs")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Completed" })).toBeInTheDocument();
  });
});
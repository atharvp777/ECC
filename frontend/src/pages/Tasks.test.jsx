import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Tasks from "./Tasks";
import { renderWithRouter } from "../test/renderWithRouter";

vi.mock("../api", () => ({
  getTasks: vi.fn(),
  createTask: vi.fn(),
  updateTask: vi.fn(),
  deleteTask: vi.fn(),
  getProjects: vi.fn(),
  linkTaskToCalendar: vi.fn(),
  unlinkTaskFromCalendar: vi.fn(),
}));

import {
  getTasks,
  createTask,
  updateTask,
  deleteTask,
  getProjects,
} from "../api";

const projects = [
  { id: 1, name: "BAJA HV" },
  { id: 2, name: "dMAT" },
];

const tasks = [
  { id: 10, title: "Finish HV wiring", priority: "high", status: "todo", deadline: null, project_id: 1 },
  { id: 11, title: "Write report", priority: "medium", status: "done", deadline: null, project_id: 2 },
];

beforeEach(() => {
  getTasks.mockResolvedValue(tasks);
  getProjects.mockResolvedValue(projects);
  createTask.mockResolvedValue({ id: 99 });
  updateTask.mockResolvedValue({});
  deleteTask.mockResolvedValue({});
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Tasks", () => {
  it("loads and renders tasks", async () => {
    renderWithRouter(<Tasks />);
    expect(await screen.findByText("Finish HV wiring")).toBeInTheDocument();
    expect(screen.getByText("Write report")).toBeInTheDocument();
    const wiringItem = screen.getByText("Finish HV wiring").closest(".task-item");
    expect(within(wiringItem).getByText("high")).toBeInTheDocument();
    expect(within(wiringItem).getByText("todo")).toBeInTheDocument();
  });

  it("shows an empty state when there are no tasks", async () => {
    getTasks.mockResolvedValue([]);
    renderWithRouter(<Tasks />);
    expect(await screen.findByText(/No tasks found/)).toBeInTheDocument();
  });

  it("shows a warning banner when the backend is unreachable", async () => {
    getTasks.mockRejectedValue(new Error("down"));
    renderWithRouter(<Tasks />);
    expect(await screen.findByText(/Couldn't load tasks/)).toBeInTheDocument();
  });

  it("creates a task through the modal", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Tasks />);
    await screen.findByText("Finish HV wiring");
    await user.click(screen.getByRole("button", { name: "New Task" }));
    await user.type(screen.getByPlaceholderText(/e.g. Finish HV wiring/), "New thermal test");
    await user.click(screen.getByRole("button", { name: "Add Task" }));
    await waitFor(() => {
      expect(createTask).toHaveBeenCalledWith(
        expect.objectContaining({ title: "New thermal test", priority: "medium", status: "todo" })
      );
    });
  });

  it("marks a task complete by toggling its check", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Tasks />);
    await screen.findByText("Finish HV wiring");
    await user.click(screen.getByRole("button", { name: "Complete Finish HV wiring" }));
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(10, { status: "done" });
    });
  });

  it("reopens a completed task", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Tasks />);
    await screen.findByText("Write report");
    await user.click(screen.getByRole("button", { name: "Reopen Write report" }));
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(11, { status: "todo" });
    });
  });

  it("deletes a task after confirmation", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Tasks />);
    await screen.findByText("Finish HV wiring");
    await user.click(screen.getByRole("button", { name: "Delete Finish HV wiring" }));
    await waitFor(() => {
      expect(deleteTask).toHaveBeenCalledWith(10);
    });
  });

  it("filters tasks by status", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Tasks />);
    await screen.findByText("Finish HV wiring");
    await user.selectOptions(screen.getAllByRole("combobox")[0], "done");
    await waitFor(() => {
      expect(getTasks).toHaveBeenCalledWith({ status: "done" });
    });
  });
});
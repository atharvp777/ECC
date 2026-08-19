import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Projects from "./Projects";
import { renderWithRouter } from "../test/renderWithRouter";

vi.mock("../api", () => ({
  getProjects: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
}));

import { getProjects, createProject, updateProject, deleteProject } from "../api";

const atLocal = (y, m, d, h = 12) => new Date(y, m, d, h).toISOString();

const projects = [
  {
    id: 1, name: "BAJA HV", category: "baja", status: "active", color: "#4f7cff",
    description: "Electric ATV development", deadline: atLocal(2026, 8, 2),
    task_count: 24, done_tasks: 12,
  },
  {
    id: 2, name: "In-SEM", category: "college", status: "on_hold", color: "#22c55e",
    description: "", deadline: null, task_count: 0, done_tasks: 0,
  },
  {
    id: 3, name: "Legacy", category: "jobprep", status: "completed", color: "#f59e0b",
    description: "", deadline: atLocal(2020, 0, 15), task_count: 3, done_tasks: 3,
  },
];

beforeEach(() => {
  getProjects.mockResolvedValue(projects);
  createProject.mockResolvedValue({ id: 9, name: "New Project" });
  updateProject.mockResolvedValue({});
  deleteProject.mockResolvedValue({});
});

describe("Projects list", () => {
  it("renders the projects index with header and rows", async () => {
    renderWithRouter(<Projects />);
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Keep your work organized.")).toBeInTheDocument();
    expect(screen.getByText("In-SEM")).toBeInTheDocument();
    expect(screen.getByText("Electric ATV development")).toBeInTheDocument();
  });

  it("displays status badges", async () => {
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("On hold")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("displays category labels", async () => {
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    expect(screen.getByText("Baja")).toBeInTheDocument();
    expect(screen.getByText("College")).toBeInTheDocument();
  });

  it("shows progress as done / total with a percentage", async () => {
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    expect(screen.getByText("12 / 24 completed")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("says 'No tasks yet' when a project has no tasks", async () => {
    renderWithRouter(<Projects />);
    await screen.findByText("In-SEM");
    expect(screen.getAllByText("No tasks yet").length).toBeGreaterThan(0);
  });

  it("shows deadlines and overdue deadlines", async () => {
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    expect(screen.getByText("Due Sep 2")).toBeInTheDocument();
    expect(screen.getByText("Overdue · Jan 15")).toBeInTheDocument();
  });

  it("shows an empty state when there are no projects", async () => {
    getProjects.mockResolvedValue([]);
    renderWithRouter(<Projects />);
    expect(await screen.findByText("No projects yet.")).toBeInTheDocument();
    expect(screen.getByText("Create your first project.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New project" }).length).toBeGreaterThan(0);
  });

  it("shows an error with a working retry when loading fails", async () => {
    getProjects.mockRejectedValueOnce(new Error("down"));
    const user = userEvent.setup();
    renderWithRouter(<Projects />);
    expect(await screen.findByText("Couldn't load projects.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
  });

  it("navigates into a project workspace when a row is clicked", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/projects"]}>
        <Routes>
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<div>PROJECT WORKSPACE</div>} />
        </Routes>
      </MemoryRouter>
    );
    await screen.findByText("BAJA HV");
    await user.click(screen.getByText("BAJA HV").closest(".project-row"));
    expect(await screen.findByText("PROJECT WORKSPACE")).toBeInTheDocument();
  });
});

describe("Project create/edit/delete", () => {
  it("creates a project through the drawer", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("button", { name: "New project" }));
    const dialog = await screen.findByRole("dialog", { name: "New project" });
    await user.type(within(dialog).getByLabelText(/Project Name/), "New Project");
    await user.selectOptions(within(dialog).getByLabelText("Category"), "jobprep");
    await user.selectOptions(within(dialog).getByLabelText("Status"), "on_hold");
    await user.click(within(dialog).getByRole("button", { name: "Create Project" }));
    await waitFor(() => {
      expect(createProject).toHaveBeenCalledWith(
        expect.objectContaining({ name: "New Project", category: "jobprep", status: "on_hold", deadline: null })
      );
    });
    expect(await screen.findByText("Project created")).toBeInTheDocument();
  });

  it("reports an error when creation fails", async () => {
    createProject.mockRejectedValueOnce(new Error("nope"));
    const user = userEvent.setup();
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("button", { name: "New project" }));
    const dialog = await screen.findByRole("dialog", { name: "New project" });
    await user.type(within(dialog).getByLabelText(/Project Name/), "New Project");
    await user.click(within(dialog).getByRole("button", { name: "Create Project" }));
    expect(await screen.findByText("Couldn't create the project.")).toBeInTheDocument();
  });

  it("edits a project through the drawer", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("button", { name: "Edit BAJA HV" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit BAJA HV" });
    const nameInput = within(dialog).getByLabelText(/Project Name/);
    await user.clear(nameInput);
    await user.type(nameInput, "BAJA HV v2");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(updateProject).toHaveBeenCalledWith(1, expect.objectContaining({ name: "BAJA HV v2" }));
    });
    expect(await screen.findByText("Project saved")).toBeInTheDocument();
  });

  it("deletes a project after explicit confirmation", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("button", { name: "Delete BAJA HV" }));
    await screen.findByText("Delete project?");
    const modal = document.querySelector(".modal");
    expect(within(modal).getByText('"BAJA HV"')).toBeInTheDocument();
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(deleteProject).toHaveBeenCalledWith(1);
    });
    expect(await screen.findByText("Project deleted")).toBeInTheDocument();
  });
});
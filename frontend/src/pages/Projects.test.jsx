import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Projects from "./Projects";
import { renderWithRouter } from "../test/renderWithRouter";

vi.mock("../api", () => ({
  getProjects: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
}));

import { getProjects, deleteProject } from "../api";

const projects = [
  { id: 1, name: "BAJA HV", category: "baja", status: "ACTIVE", task_count: 5, done_tasks: 2, color: "#4f7cff", description: "High voltage", deadline: null },
  { id: 2, name: "In-SEM", category: "college", status: "ACTIVE", task_count: 0, done_tasks: 0, color: "#22c55e", description: "", deadline: null },
];

beforeEach(() => {
  getProjects.mockResolvedValue(projects);
  deleteProject.mockResolvedValue({});
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Projects", () => {
  it("loads and displays projects", async () => {
    renderWithRouter(<Projects />);
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
    expect(screen.getByText("In-SEM")).toBeInTheDocument();
    expect(screen.getByText(/Baja · ACTIVE/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no projects", async () => {
    getProjects.mockResolvedValue([]);
    renderWithRouter(<Projects />);
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument();
  });

  it("shows a warning banner when the backend is unreachable", async () => {
    getProjects.mockRejectedValue(new Error("down"));
    renderWithRouter(<Projects />);
    expect(await screen.findByText(/Couldn't load projects/)).toBeInTheDocument();
  });

  it("navigates into a project when its card is clicked", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/projects"]}>
        <Routes>
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<div>PROJECT PAGE</div>} />
        </Routes>
      </MemoryRouter>
    );
    await screen.findByText("BAJA HV");
    await user.click(screen.getByText("BAJA HV"));
    expect(await screen.findByText("PROJECT PAGE")).toBeInTheDocument();
  });

  it("deletes a project after confirmation", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Projects />);
    await screen.findByText("BAJA HV");
    const card = screen.getByText("BAJA HV").closest(".project-card");
    await user.click(card.querySelector("button"));
    await waitFor(() => {
      expect(deleteProject).toHaveBeenCalledWith(1);
    });
  });
});
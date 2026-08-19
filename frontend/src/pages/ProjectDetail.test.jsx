import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import ProjectDetail from "./ProjectDetail";

vi.mock("../api", () => ({
  getProjects: vi.fn(),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  getTasks: vi.fn(),
  createTask: vi.fn(),
  updateTask: vi.fn(),
  deleteTask: vi.fn(),
  linkTaskToCalendar: vi.fn(),
  unlinkTaskFromCalendar: vi.fn(),
  getNotes: vi.fn(),
  createNote: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  getDocumentDownloadUrl: vi.fn(),
}));

import {
  getProject, getProjects, getTasks, createTask, updateTask, deleteTask,
  getDocuments, uploadDocument, deleteDocument,
  getNotes, createNote, updateNote, deleteNote,
} from "../api";

const atLocal = (y, m, d, h = 12) => new Date(y, m, d, h).toISOString();

const project = {
  id: 1, name: "BAJA HV", category: "baja", status: "active", color: "#4f7cff",
  description: "Electric ATV development", deadline: atLocal(2026, 8, 2),
  task_count: 3, done_tasks: 1, overdue_tasks: 1, total_tasks: 3,
  created_at: atLocal(2026, 1, 1), updated_at: atLocal(2026, 2, 1),
};

const tasks = [
  { id: 1, title: "Design battery tray", status: "todo", priority: "high", deadline: atLocal(2020, 0, 1, 10), project_id: 1, created_at: atLocal(2026, 1, 1), updated_at: atLocal(2026, 1, 2) },
  { id: 2, title: "Review wiring", status: "done", priority: "medium", deadline: null, project_id: 1, completed_at: atLocal(2026, 2, 1), created_at: atLocal(2026, 1, 3), updated_at: atLocal(2026, 2, 1) },
  { id: 3, title: "Order parts", status: "in_progress", priority: "critical", deadline: atLocal(2026, 7, 21, 10), project_id: 1, created_at: atLocal(2026, 1, 4), updated_at: atLocal(2026, 1, 5) },
];

const docs = [
  { id: 1, title: "Spec.pdf", original_filename: "spec.pdf", mime_type: "application/pdf", file_size_bytes: 2048, created_at: atLocal(2026, 1, 6), updated_at: atLocal(2026, 1, 6), project_id: 1 },
];

const notes = [
  { id: 1, title: "Kickoff notes", content: "Decided on battery chemistry and cell layout.", updated_at: atLocal(2026, 1, 7), created_at: atLocal(2026, 1, 7), project_id: 1 },
];

const projectsList = [project, { id: 2, name: "In-SEM", category: "college", status: "active", color: "#22c55e" }];

function renderDetail(route = "/projects/1") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/projects" element={<div>PROJECTS PAGE</div>} />
        <Route path="/projects/:id" element={<ProjectDetail />} />
        <Route path="/projects/:id/tasks" element={<ProjectDetail />} />
        <Route path="/projects/:id/documents" element={<ProjectDetail />} />
        <Route path="/projects/:id/notes" element={<ProjectDetail />} />
        <Route path="/projects/:id/ai" element={<ProjectDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  getProject.mockResolvedValue(project);
  getProjects.mockResolvedValue(projectsList);
  getTasks.mockResolvedValue(tasks);
  getDocuments.mockResolvedValue(docs);
  getNotes.mockResolvedValue(notes);
  createTask.mockResolvedValue({ id: 10, title: "New task" });
  updateTask.mockResolvedValue({});
  deleteTask.mockResolvedValue({});
  uploadDocument.mockResolvedValue({});
  deleteDocument.mockResolvedValue({});
  createNote.mockResolvedValue(notes[0]);
  updateNote.mockResolvedValue({});
  deleteNote.mockResolvedValue({});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Project workspace header", () => {
  it("renders the workspace header with name, description, and metadata", async () => {
    renderDetail();
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
    expect(screen.getByText("Electric ATV development")).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Baja").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Due Sep 2").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add task" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask Orbit" })).toBeInTheDocument();
  });

  it("shows progress in the header", async () => {
    renderDetail();
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
    expect(screen.getAllByText("1 / 3 completed").length).toBeGreaterThan(0);
    expect(screen.getByText("33%")).toBeInTheDocument();
  });

  it("requests only this project's tasks, documents, and notes", async () => {
    renderDetail();
    await screen.findByText("BAJA HV");
    expect(getTasks).toHaveBeenCalledWith({ project_id: "1" });
    expect(getDocuments).toHaveBeenCalledWith({ project_id: "1" });
    expect(getNotes).toHaveBeenCalledWith({ project_id: "1" });
  });

  it("shows the tabs and renders the overview tab by default", async () => {
    renderDetail();
    await screen.findByText("BAJA HV");
    for (const name of ["Overview", "Tasks", "Documents", "Notes", "Orbit AI"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("2 open · 1 completed")).toBeInTheDocument();
    expect(screen.getByText("1 document")).toBeInTheDocument();
    expect(screen.getByText("1 note")).toBeInTheDocument();
  });

  it("returns to the projects list via the back link", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByText("PROJECTS PAGE")).toBeInTheDocument();
  });

  it("shows a skeleton while loading", async () => {
    let resolveProject;
    getProject.mockReturnValue(new Promise((res) => { resolveProject = res; }));
    renderDetail();
    expect(document.querySelector(".project-load")).toBeInTheDocument();
    resolveProject(project);
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
  });

  it("shows an error with a working retry when loading fails", async () => {
    getProject.mockRejectedValueOnce(new Error("down"));
    const user = userEvent.setup();
    renderDetail();
    expect(await screen.findByText("Couldn't load this project.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("BAJA HV")).toBeInTheDocument();
  });

  it("shows Project not found for a missing project", async () => {
    getProject.mockRejectedValueOnce({ response: { status: 404 } });
    const user = userEvent.setup();
    renderDetail();
    expect(await screen.findByText("Project not found.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Projects" }));
    expect(await screen.findByText("PROJECTS PAGE")).toBeInTheDocument();
  });
});

describe("Project tabs", () => {
  it("navigates tabs with arrow keys", async () => {
    renderDetail();
    await screen.findByText("BAJA HV");
    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    overviewTab.focus();
    fireEvent.keyDown(overviewTab, { key: "ArrowRight" });
    expect(await screen.findByText("Design battery tray")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tasks" })).toHaveFocus();
  });

  it("shows empty documents and notes states", async () => {
    getDocuments.mockResolvedValue([]);
    getNotes.mockResolvedValue([]);
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("tab", { name: "Documents" }));
    expect(await screen.findByText("No documents yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Notes" }));
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
  });
});

describe("Project tasks tab", () => {
  async function openTasks() {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("tab", { name: "Tasks" }));
    await screen.findByText("Design battery tray");
    return user;
  }

  it("lists this project's tasks in Open and Completed groups", async () => {
    await openTasks();
    expect(screen.getByText("Order parts")).toBeInTheDocument();
    expect(screen.getByText("Review wiring")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Open/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Completed/ })).toBeInTheDocument();
  });

  it("completes a task through its checkbox", async () => {
    const user = await openTasks();
    await user.click(screen.getByRole("button", { name: "Complete Order parts" }));
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(3, { status: "done" });
    });
  });

  it("opens a task in the drawer from its row", async () => {
    const user = await openTasks();
    await user.click(screen.getByText("Order parts").closest(".task-body"));
    const dialog = await screen.findByRole("dialog", { name: "Order parts" });
    expect(within(dialog).getByText("In progress")).toBeInTheDocument();
  });

  it("creates a task that preselects this project", async () => {
    const user = await openTasks();
    await user.click(screen.getByRole("button", { name: "Add task" }));
    const dialog = await screen.findByRole("dialog", { name: "New task" });
    expect(within(dialog).getByLabelText("Project")).toHaveValue("1");
    await user.type(within(dialog).getByLabelText(/Task Title/), "Assemble the harness");
    await user.click(within(dialog).getByRole("button", { name: "Add Task" }));
    await waitFor(() => {
      expect(createTask).toHaveBeenCalledWith(expect.objectContaining({ project_id: 1, title: "Assemble the harness" }));
    });
  });

  it("deletes a task after confirmation", async () => {
    const user = await openTasks();
    await user.click(screen.getByRole("button", { name: "Delete Design battery tray" }));
    await screen.findByText("Delete task?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(deleteTask).toHaveBeenCalledWith(1);
    });
  });
});

describe("Project documents tab", () => {
  async function openDocuments() {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("tab", { name: "Documents" }));
    await screen.findByText("Spec.pdf");
    return user;
  }

  it("lists documents with type, size, and date", async () => {
    await openDocuments();
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload document" })).toBeInTheDocument();
  });

  it("uploads a document scoped to this project", async () => {
    await openDocuments();
    const input = document.querySelector('input[type="file"]');
    const file = new File(["pdf"], "spec.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      expect(uploadDocument).toHaveBeenCalled();
    });
    expect(uploadDocument.mock.calls[0][0].get("project_id")).toBe("1");
  });

  it("deletes a document after confirmation", async () => {
    const user = await openDocuments();
    await user.click(screen.getByRole("button", { name: "Delete Spec.pdf" }));
    await screen.findByText("Delete document?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(deleteDocument).toHaveBeenCalledWith(1);
    });
  });
});

describe("Project notes tab", () => {
  async function openNotes() {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Kickoff notes");
    return user;
  }

  it("lists notes associated with this project", async () => {
    await openNotes();
    expect(screen.getByText(/Decided on battery chemistry/)).toBeInTheDocument();
  });

  it("creates a note scoped to this project", async () => {
    const user = await openNotes();
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => {
      expect(createNote).toHaveBeenCalledWith({ title: "Untitled note", content: "", project_id: 1 });
    });
  });

  it("edits a note", async () => {
    const user = await openNotes();
    await user.click(screen.getByRole("button", { name: "Edit Kickoff notes" }));
    const title = screen.getByLabelText("Note title");
    await user.clear(title);
    await user.type(title, "Kickoff decisions");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(updateNote).toHaveBeenCalledWith(1, expect.objectContaining({ title: "Kickoff decisions" }));
    });
  });

  it("deletes a note after confirmation", async () => {
    const user = await openNotes();
    await user.click(screen.getByRole("button", { name: "Delete Kickoff notes" }));
    await screen.findByText("Delete note?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(deleteNote).toHaveBeenCalledWith(1);
    });
  });
});

describe("Project Orbit AI tab", () => {
  async function openAi() {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("BAJA HV");
    await user.click(screen.getByRole("tab", { name: "Orbit AI" }));
    await screen.findByText("Ask anything about this project.");
    return user;
  }

  it("shows contextual example prompts", async () => {
    await openAi();
    for (const prompt of ["What should I work on next?", "Summarize this project.", "What documents do I have?", "What's overdue?"]) {
      expect(screen.getByRole("button", { name: prompt })).toBeInTheDocument();
    }
  });

  it("sends a project-scoped message through the chat API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ reply: "Here is your project summary." }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = await openAi();
    await user.type(screen.getByLabelText("Project AI message"), "Summarize the project");
    await user.click(screen.getByRole("button", { name: /Send/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.messages[0].content).toContain("BAJA HV");
    expect(body.messages).toContainEqual(expect.objectContaining({ role: "user", content: "Summarize the project" }));
    expect(await screen.findByText("Here is your project summary.")).toBeInTheDocument();
  });

  it("sends the project id as an explicit context signal with no binary payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ reply: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = await openAi();
    await user.type(screen.getByLabelText("Project AI message"), "Summarize the project");
    await user.click(screen.getByRole("button", { name: /Send/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.project_id).toBe(1);
    // The request body carries only text messages — image bytes never leave the
    // backend and never enter the chat history that the UI stores.
    for (const message of body.messages) {
      expect(typeof message.content).toBe("string");
      expect(message.content).not.toContain("inline_data");
      expect(message.content).not.toContain("data:");
    }
    expect(JSON.stringify(body)).not.toMatch(/\\u0000|base64|image\/(png|jpeg|webp)/);
  });
});
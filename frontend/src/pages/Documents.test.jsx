import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Documents from "./Documents";
import { renderWithRouter } from "../test/renderWithRouter";

vi.mock("../api", () => ({
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  getProjects: vi.fn(),
  searchDocs: vi.fn(),
  askDocs: vi.fn(),
  ingestDoc: vi.fn(),
  indexStatus: vi.fn(),
  getDocumentDownloadUrl: vi.fn((id) => `http://localhost:8000/documents/${id}/download`),
}));

import { getDocuments, getProjects, uploadDocument, deleteDocument, indexStatus } from "../api";

const docs = [
  {
    id: 1,
    title: "BE SEM 1 Syllabus",
    original_filename: "BE SEM 1 Syllabus.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 777195,
    project_id: 3,
    created_at: "2026-08-01T10:00:00",
  },
  {
    id: 2,
    title: "",
    original_filename: "notes.txt",
    mime_type: "text/plain",
    file_size_bytes: 2048,
    project_id: null,
    created_at: "2026-08-02T10:00:00",
  },
];

const projects = [
  { id: 1, name: "BAJA HV" },
  { id: 2, name: "dMAT" },
  { id: 3, name: "In-SEM" },
];

beforeEach(() => {
  getDocuments.mockResolvedValue(docs);
  getProjects.mockResolvedValue(projects);
  indexStatus.mockResolvedValue({ indexed_chunks: 12, documents: [{ doc_id: 1 }] });
  uploadDocument.mockResolvedValue({});
  deleteDocument.mockResolvedValue({});
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Documents", () => {
  it("loads and displays documents", async () => {
    renderWithRouter(<Documents />);
    expect(await screen.findByText("BE SEM 1 Syllabus")).toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.getByText(/12 chunks indexed/)).toBeInTheDocument();
    expect(screen.getByText("✓ indexed")).toBeInTheDocument();
  });

  it("shows an empty state when there are no documents", async () => {
    getDocuments.mockResolvedValue([]);
    renderWithRouter(<Documents />);
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument();
  });

  it("shows a warning banner when the backend is unreachable", async () => {
    getDocuments.mockRejectedValue(new Error("down"));
    renderWithRouter(<Documents />);
    expect(await screen.findByText(/Couldn't load documents/)).toBeInTheDocument();
  });

  it("uploads a file", async () => {
    const user = userEvent.setup();
    const { container } = renderWithRouter(<Documents />);
    await screen.findByText("BE SEM 1 Syllabus");
    const fileInput = container.querySelector('input[type="file"]');
    const file = new File(["hello"], "report.pdf", { type: "application/pdf" });
    const changeEvent = new Event("change", { bubbles: true });
    Object.defineProperty(fileInput, "files", { value: [file] });
    fileInput.dispatchEvent(changeEvent);
    await waitFor(() => {
      expect(uploadDocument).toHaveBeenCalledWith(expect.any(FormData));
    });
  });

  it("deletes a document after confirmation", async () => {
    const user = userEvent.setup();
    renderWithRouter(<Documents />);
    await screen.findByText("BE SEM 1 Syllabus");
    await user.click(screen.getByRole("button", { name: "Delete BE SEM 1 Syllabus" }));
    await waitFor(() => {
      expect(deleteDocument).toHaveBeenCalledWith(1);
    });
  });
});
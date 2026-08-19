import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within, fireEvent } from "@testing-library/react";
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

import {
  getDocuments,
  getProjects,
  uploadDocument,
  deleteDocument,
  searchDocs,
  askDocs,
  indexStatus,
} from "../api";

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
  {
    id: 3,
    title: "HV Diagram",
    original_filename: "HV Diagram.png",
    mime_type: "image/png",
    file_size_bytes: 3145728,
    project_id: 1,
    created_at: "2026-08-03T10:00:00",
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
  indexStatus.mockResolvedValue({ indexed_chunks: 12, documents: [{ doc_id: 1 }, { doc_id: 3 }] });
  uploadDocument.mockResolvedValue({});
  deleteDocument.mockResolvedValue({});
  searchDocs.mockResolvedValue([{ score: 0.92, doc_id: 1, title: "rulebook.pdf", text: "HV battery pack must be isolated." }]);
  askDocs.mockResolvedValue({ answer: "Store HV packs in a dry area.", sources: ["rulebook.pdf", "spec.pdf"] });

  if (typeof URL.createObjectURL !== "function") {
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  }
});

async function renderLibrary() {
  renderWithRouter(<Documents />);
  await screen.findByText("BE SEM 1 Syllabus");
}

describe("Knowledge Library", () => {
  it("loads and displays documents with metadata and status", async () => {
    await renderLibrary();
    expect(screen.getByText("Knowledge Library")).toBeInTheDocument();
    expect(screen.getByText(/3 documents/)).toBeInTheDocument();
    expect(screen.getByText(/12 chunks indexed/)).toBeInTheDocument();
    expect(screen.getAllByText("Ready")).toHaveLength(2);
    expect(screen.getByText("Pending")).toBeInTheDocument();
    const list = within(document.querySelector(".doc-list"));
    expect(list.getByText("In-SEM")).toBeInTheDocument();
    expect(list.getByText("PDF")).toBeInTheDocument();
    expect(list.getByText("TXT")).toBeInTheDocument();
    expect(list.getByText("PNG")).toBeInTheDocument();
    expect(list.getByText("3.0 MB")).toBeInTheDocument();
    expect(list.getByText("Aug 3")).toBeInTheDocument();
  });

  it("shows a loading skeleton while documents load", async () => {
    getDocuments.mockReturnValue(new Promise(() => {}));
    getProjects.mockReturnValue(new Promise(() => {}));
    indexStatus.mockReturnValue(new Promise(() => {}));
    renderWithRouter(<Documents />);
    expect(screen.getByRole("status", { name: "Loading documents" })).toBeInTheDocument();
    expect(document.querySelectorAll(".doc-row--skeleton").length).toBeGreaterThan(0);
  });

  it("shows an error with a working retry when loading fails", async () => {
    getDocuments.mockRejectedValueOnce(new Error("down"));
    renderWithRouter(<Documents />);
    expect(await screen.findByText("Couldn't load documents.")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("BE SEM 1 Syllabus")).toBeInTheDocument();
  });

  it("shows an empty library state", async () => {
    getDocuments.mockResolvedValue([]);
    renderWithRouter(<Documents />);
    expect(await screen.findByText("Your knowledge library is empty.")).toBeInTheDocument();
    expect(screen.getByText("Upload your first engineering document to get started.")).toBeInTheDocument();
  });

  it("searches documents by filename", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.type(screen.getByLabelText("Search documents"), "syllabus");
    expect(screen.getByText("BE SEM 1 Syllabus")).toBeInTheDocument();
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("HV Diagram")).not.toBeInTheDocument();
  });

  it("filters by project", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), "1");
    expect(screen.getByText("HV Diagram")).toBeInTheDocument();
    expect(screen.queryByText("BE SEM 1 Syllabus")).not.toBeInTheDocument();
  });

  it("filters by type", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.selectOptions(screen.getByRole("combobox", { name: "Type" }), "PDF");
    expect(screen.getByText("BE SEM 1 Syllabus")).toBeInTheDocument();
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("HV Diagram")).not.toBeInTheDocument();
  });

  it("composes search with project and type filters", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.type(screen.getByLabelText("Search documents"), "hv");
    await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), "1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Type" }), "PNG");
    expect(screen.getByText("HV Diagram")).toBeInTheDocument();
    expect(screen.queryByText("BE SEM 1 Syllabus")).not.toBeInTheDocument();
  });

  it("shows no-match state and clears filters", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.type(screen.getByLabelText("Search documents"), "zzzz");
    expect(await screen.findByText("No documents match your filters.")).toBeInTheDocument();
    const empty = within(document.querySelector(".orbit-empty"));
    await user.click(empty.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("BE SEM 1 Syllabus")).toBeInTheDocument();
    expect(screen.getByText(/3 documents/)).toBeInTheDocument();
  });

  it("opens the upload drawer from the toolbar", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Upload document" }));
    expect(screen.getByRole("dialog", { name: "Upload document" })).toBeInTheDocument();
  });

  it("uploads a document with an optional project and reports success", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Upload document" }));
    const dialog = screen.getByRole("dialog", { name: "Upload document" });

    const input = within(dialog).getByLabelText("Choose file to upload");
    const file = new File(["pdf"], "report.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Project (optional)" }), "1");
    await user.click(within(dialog).getByRole("button", { name: "Upload document" }));

    await waitFor(() => {
      expect(uploadDocument).toHaveBeenCalledWith(expect.any(FormData));
    });
    const fd = uploadDocument.mock.calls[0][0];
    expect(fd.get("project_id")).toBe("1");
    expect(fd.get("file")).toBe(file);
    expect(await screen.findByText("Document uploaded")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Upload document" })).not.toBeInTheDocument();
  });

  it("keeps the upload drawer open with an honest error on failure", async () => {
    const user = userEvent.setup();
    uploadDocument.mockRejectedValueOnce({ response: { data: { detail: "File type not allowed." } } });
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Upload document" }));
    const dialog = screen.getByRole("dialog", { name: "Upload document" });
    const input = within(dialog).getByLabelText("Choose file to upload");
    fireEvent.change(input, { target: { files: [new File(["x"], "x.bin", { type: "application/octet-stream" })] } });
    await user.click(within(dialog).getByRole("button", { name: "Upload document" }));
    expect(await screen.findByText("File type not allowed.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Upload document" })).toBeInTheDocument();
  });

  it("opens a preview for PDF documents", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(["%PDF"], { type: "application/pdf" })),
    });
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Preview BE SEM 1 Syllabus" }));
    expect(await within(document.querySelector(".doc-preview")).findByTitle("BE SEM 1 Syllabus")).toBeInTheDocument();
  });

  it("renders text documents as text in preview", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(["hello knowledge"], { type: "text/plain" })),
    });
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Preview notes.txt" }));
    expect(await screen.findByText("hello knowledge")).toBeInTheDocument();
  });

  it("provides download and delete actions on every row", async () => {
    await renderLibrary();
    const download = screen.getByRole("link", { name: "Download BE SEM 1 Syllabus" });
    expect(download).toHaveAttribute("href", "http://localhost:8000/documents/1/download");
    expect(screen.getByRole("button", { name: "Delete BE SEM 1 Syllabus" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview BE SEM 1 Syllabus" })).toBeInTheDocument();
  });

  it("asks Orbit and renders the answer", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Ask Orbit" }));
    const dialog = screen.getByRole("dialog", { name: "Ask Orbit" });
    await user.type(within(dialog).getByRole("textbox", { name: /Ask a question/ }), "battery safety?");
    await user.click(within(dialog).getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Store HV packs in a dry area.")).toBeInTheDocument();
    expect(askDocs).toHaveBeenCalledWith("battery safety?");
  });

  it("renders knowledge sources returned by the API", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Ask Orbit" }));
    const dialog = screen.getByRole("dialog", { name: "Ask Orbit" });
    await user.type(within(dialog).getByRole("textbox", { name: /Ask a question/ }), "rules?");
    await user.click(within(dialog).getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Sources: rulebook.pdf · spec.pdf")).toBeInTheDocument();
  });

  it("searches knowledge semantically with chunk scores", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Ask Orbit" }));
    const dialog = screen.getByRole("dialog", { name: "Ask Orbit" });
    await user.click(within(dialog).getByRole("button", { name: "Search knowledge" }));
    await user.type(within(dialog).getByRole("textbox", { name: /Search your documents/ }), "battery");
    await user.click(within(dialog).getByRole("button", { name: "Search" }));
    expect(await screen.findByText("rulebook.pdf")).toBeInTheDocument();
    expect(screen.getByText("score: 0.920")).toBeInTheDocument();
    expect(searchDocs).toHaveBeenCalledWith("battery", 5);
  });

  it("shows an honest error when the knowledge service is unreachable", async () => {
    const user = userEvent.setup();
    askDocs.mockRejectedValueOnce(new Error("down"));
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Ask Orbit" }));
    const dialog = screen.getByRole("dialog", { name: "Ask Orbit" });
    await user.type(within(dialog).getByRole("textbox", { name: /Ask a question/ }), "rules?");
    await user.click(within(dialog).getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/Couldn't reach the knowledge service/)).toBeInTheDocument();
  });

  it("closes drawers with Escape and restores focus", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    const uploadBtn = screen.getByRole("button", { name: "Upload document" });
    await user.click(uploadBtn);
    expect(screen.getByRole("dialog", { name: "Upload document" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Upload document" })).not.toBeInTheDocument();
    expect(uploadBtn).toHaveFocus();
  });

  it("deletes a document after confirmation and reports success", async () => {
    const user = userEvent.setup();
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Delete BE SEM 1 Syllabus" }));
    await screen.findByText("Delete document?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(deleteDocument).toHaveBeenCalledWith(1);
    });
    expect(await screen.findByText("Document deleted")).toBeInTheDocument();
  });

  it("keeps the document and reports an honest error when deletion fails", async () => {
    const user = userEvent.setup();
    deleteDocument.mockRejectedValueOnce(new Error("down"));
    await renderLibrary();
    await user.click(screen.getByRole("button", { name: "Delete BE SEM 1 Syllabus" }));
    await screen.findByText("Delete document?");
    const modal = document.querySelector(".modal");
    await user.click(within(modal).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Couldn't delete the document.")).toBeInTheDocument();
    expect(screen.getByText("BE SEM 1 Syllabus")).toBeInTheDocument();
  });

  it("renders rows with responsive-safe structure", async () => {
    await renderLibrary();
    expect(document.querySelectorAll(".doc-row").length).toBe(3);
    expect(document.querySelectorAll(".doc-row .doc-row__meta").length).toBe(3);
  });
});
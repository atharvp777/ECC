import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Chat from "./Chat";
import { renderWithRouter } from "../test/renderWithRouter";

const STATUS_OK = { ok: true, status: 200, headers: { get: () => "application/json" } };

function mockFetch({ status = "ok", reply = "", errorMessage = "", networkError = false } = {}) {
  if (networkError) {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    return;
  }
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url) => {
      if (url.endsWith("/api/chat/status")) {
        return Promise.resolve({
          ...STATUS_OK,
          json: () => Promise.resolve({ display: "gemini/gemini-3.5-flash-lite" }),
        });
      }
      if (url.endsWith("/api/chat/")) {
        if (status === "error") {
          return Promise.resolve({
            ok: false,
            status: 500,
            headers: { get: () => "application/json" },
            json: () => Promise.resolve({ detail: errorMessage || "backend exploded" }),
          });
        }
        return Promise.resolve({
          ...STATUS_OK,
          json: () => Promise.resolve({ reply, sources: [] }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, headers: { get: () => "application/json" } });
    })
  );
}

async function sendMessage(text = "Hello") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Message input"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

beforeEach(() => {
  sessionStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("Chat", () => {
  it("renders the header and initial greeting", async () => {
    renderWithRouter(<Chat />);
    expect(screen.getByText("AI Chat")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Hey Atharv/)).toBeInTheDocument();
    });
  });

  it("shows the model indicator from the status endpoint", async () => {
    renderWithRouter(<Chat />);
    await waitFor(() => {
      expect(screen.getByText("gemini/gemini-3.5-flash-lite")).toBeInTheDocument();
    });
  });

  it("shows an Online pill when the backend is reachable", async () => {
    renderWithRouter(<Chat />);
    await waitFor(() => {
      expect(screen.getByText("Online")).toBeInTheDocument();
    });
  });

  it("shows an Offline pill when the backend is unreachable", async () => {
    mockFetch({ networkError: true });
    renderWithRouter(<Chat />);
    await waitFor(() => {
      expect(screen.getByText("Offline")).toBeInTheDocument();
    });
  });

  it("renders the user message and the AI reply after sending", async () => {
    mockFetch({ reply: "Here are your tasks: 3 open." });
    renderWithRouter(<Chat />);
    await sendMessage("List my tasks");
    expect(await screen.findByText("List my tasks")).toBeInTheDocument();
    expect(await screen.findByText("Here are your tasks: 3 open.")).toBeInTheDocument();
  });

  it("shows a loading state while the request is in flight", async () => {
    let resolveRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url) => {
        if (url.endsWith("/api/chat/status")) {
          return Promise.resolve({ ...STATUS_OK, json: () => Promise.resolve({ display: "x" }) });
        }
        return new Promise((res) => {
          resolveRequest = () =>
            res({ ...STATUS_OK, json: () => Promise.resolve({ reply: "done", sources: [] }) });
        });
      })
    );
    renderWithRouter(<Chat />);
    await sendMessage("hello");
    expect(screen.getByRole("button", { name: "Sending..." })).toBeInTheDocument();
    expect(screen.getByLabelText("Message input")).toBeDisabled();
    resolveRequest();
    expect(await screen.findByText("done")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("renders a backend error message when the response is not ok", async () => {
    mockFetch({ status: "error", errorMessage: "Model quota exceeded" });
    renderWithRouter(<Chat />);
    await sendMessage("hello");
    expect(await screen.findByText("Model quota exceeded")).toBeInTheDocument();
  });

  it("renders a backend-unreachable message on network failure", async () => {
    mockFetch({ networkError: true });
    renderWithRouter(<Chat />);
    await sendMessage("hello");
    expect(
      await screen.findByText(/Couldn't reach the backend/)
    ).toBeInTheDocument();
  });

  it("clears the conversation back to the greeting", async () => {
    mockFetch({ reply: "a reply" });
    renderWithRouter(<Chat />);
    await sendMessage("hello");
    await screen.findByText("a reply");
    await userEvent.click(screen.getByRole("button", { name: "Clear Chat" }));
    expect(screen.getByText(/Hey Atharv/)).toBeInTheDocument();
    expect(screen.queryByText("a reply")).not.toBeInTheDocument();
    expect(screen.queryByText("hello")).not.toBeInTheDocument();
  });

  it("renders tool/action results such as a bulk update summary", async () => {
    mockFetch({ reply: "Updated 1 task (priority set to critical)." });
    renderWithRouter(<Chat />);
    await sendMessage("prioritize it");
    expect(await screen.findByText("Updated 1 task (priority set to critical).")).toBeInTheDocument();
  });

  it("renders document-aware markdown responses", async () => {
    mockFetch({
      reply:
        "The syllabus covers **HV systems**.\n\n- Subjects: SEM\n- Page: 3\n\nSources: BE SEM 1 Syllabus.pdf",
    });
    renderWithRouter(<Chat />);
    await sendMessage("What subjects are in the syllabus?");
    expect(await screen.findByText(/The syllabus covers/)).toBeInTheDocument();
    expect(screen.getByText(/Sources: BE SEM 1 Syllabus/)).toBeInTheDocument();
    expect(screen.getByText(/Subjects: SEM/)).toBeInTheDocument();
  });
});
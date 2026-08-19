import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, render, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Chat from "./Chat";
import {
  getProjects,
  getTasks,
  getDocuments,
  getIntegrationStatus,
} from "../api";

vi.mock("../api", () => ({
  getProjects: vi.fn(),
  getTasks: vi.fn(),
  getDocuments: vi.fn(),
  getIntegrationStatus: vi.fn(),
}));

const STATUS_OK = { ok: true, status: 200, headers: { get: () => "application/json" } };

const CONTEXT = {
  projects: [
    { id: 1, name: "In-SEM" },
    { id: 2, name: "BAJA HV" },
  ],
  tasks: [
    { id: 1, title: "Submit lab manual", status: "todo" },
    { id: 2, title: "Overdue battery report", status: "in_progress" },
    { id: 3, title: "Finished item", status: "done" },
  ],
  documents: [{ id: 1, title: "BE SEM 1 Syllabus" }],
};

function fetchPostCalls() {
  return fetch.mock.calls.filter(([url]) => String(url).endsWith("/api/chat/"));
}

function mockFetch({
  status = "ok",
  reply = "",
  errorMessage = "",
  networkError = false,
  configured = true,
} = {}) {
  if (networkError) {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    return;
  }
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url) => {
      if (String(url).endsWith("/api/chat/status")) {
        return Promise.resolve({
          ...STATUS_OK,
          json: () => Promise.resolve({ configured, display: "orbit" }),
        });
      }
      if (String(url).endsWith("/api/chat/")) {
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

function renderChat(route = "/chat") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/chat" element={<Chat />} />
        <Route path="/calendar" element={<div>CALENDAR PAGE</div>} />
        <Route path="/tasks" element={<div>TASKS PAGE</div>} />
        <Route path="/projects" element={<div>PROJECTS PAGE</div>} />
        <Route path="/projects/:id/ai" element={<div>PROJECT AI PAGE</div>} />
      </Routes>
    </MemoryRouter>
  );
}

async function sendMessage(text = "Hello") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Message Orbit"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  getProjects.mockResolvedValue(CONTEXT.projects);
  getTasks.mockResolvedValue(CONTEXT.tasks);
  getDocuments.mockResolvedValue(CONTEXT.documents);
  getIntegrationStatus.mockResolvedValue({ google_calendar: true });
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("Chat — Orbit AI workspace", () => {
  it("renders the Orbit AI header and subtitle", async () => {
    renderChat();
    expect(screen.getByRole("heading", { name: /Orbit AI/ })).toBeInTheDocument();
    expect(screen.getByText("Your intelligent engineering workspace.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("AI online")).toBeInTheDocument());
  });

  it("shows AI online when the provider is configured", async () => {
    renderChat();
    expect(await screen.findByText("AI online")).toBeInTheDocument();
  });

  it("shows AI unavailable when the provider is not configured", async () => {
    mockFetch({ configured: false });
    renderChat();
    expect(await screen.findByText("AI unavailable")).toBeInTheDocument();
  });

  it("shows the time-based empty-state greeting and all suggestions", async () => {
    renderChat();
    expect(
      screen.getByText(/Good (morning|afternoon|evening)\. What are we working on\?/)
    ).toBeInTheDocument();
    [
      "Plan my day",
      "What's most important today?",
      "Create a task",
      "Summarize a project",
      "Search my knowledge",
      "Check my calendar",
    ].forEach((suggestion) => {
      expect(screen.getByRole("button", { name: suggestion })).toBeInTheDocument();
    });
    await waitFor(() => expect(screen.getByText("AI online")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("2 open tasks")).toBeInTheDocument());
  });

  it("sends a chat request when a suggestion is clicked", async () => {
    mockFetch({ reply: "Here's today's focus." });
    renderChat();
    await userEvent.click(screen.getByRole("button", { name: "Plan my day" }));
    expect(await screen.findByText("Here's today's focus.")).toBeInTheDocument();
    expect(fetchPostCalls()).toHaveLength(1);
    const body = JSON.parse(fetchPostCalls()[0][1].body);
    expect(body.messages).toContainEqual({ role: "user", content: "Plan my day" });
  });

  it("renders the user message and the Orbit reply after sending", async () => {
    mockFetch({ reply: "Here are your tasks: 3 open." });
    renderChat();
    await sendMessage("List my tasks");
    expect(await screen.findByText("List my tasks")).toBeInTheDocument();
    expect(await screen.findByText("Here are your tasks: 3 open.")).toBeInTheDocument();
  });

  it("sends with Enter and inserts a newline with Shift+Enter", async () => {
    mockFetch({ reply: "ok" });
    const user = userEvent.setup();
    renderChat();
    const input = screen.getByLabelText("Message Orbit");
    await user.type(input, "line one{Shift>}{Enter}{/Shift}line two");
    expect(input.value).toBe("line one\nline two");
    expect(fetchPostCalls()).toHaveLength(0);
    await user.type(input, "{Enter}");
    expect(await screen.findByText("ok")).toBeInTheDocument();
    expect(fetchPostCalls()).toHaveLength(1);
  });

  it("blocks sending an empty message", async () => {
    renderChat();
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    await userEvent.click(send);
    expect(fetchPostCalls()).toHaveLength(0);
  });

  it("blocks sending a whitespace-only message", async () => {
    renderChat();
    await userEvent.type(screen.getByLabelText("Message Orbit"), "   ");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("blocks duplicate submission while a request is in flight", async () => {
    let resolveRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url) => {
        if (String(url).endsWith("/api/chat/status")) {
          return Promise.resolve({ ...STATUS_OK, json: () => Promise.resolve({ configured: true, display: "x" }) });
        }
        return new Promise((res) => {
          resolveRequest = () =>
            res({ ...STATUS_OK, json: () => Promise.resolve({ reply: "done", sources: [] }) });
        });
      })
    );
    renderChat();
    await sendMessage("hello");
    expect(screen.getByRole("button", { name: "Thinking…" })).toBeInTheDocument();
    expect(screen.getByLabelText("Message Orbit")).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Thinking…" }));
    expect(fetchPostCalls()).toHaveLength(1);
    resolveRequest();
    expect(await screen.findByText("done")).toBeInTheDocument();
    expect(fetchPostCalls()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("announces the thinking state while loading", async () => {
    let resolveRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url) => {
        if (String(url).endsWith("/api/chat/status")) {
          return Promise.resolve({ ...STATUS_OK, json: () => Promise.resolve({ configured: true, display: "x" }) });
        }
        return new Promise((res) => {
          resolveRequest = () =>
            res({ ...STATUS_OK, json: () => Promise.resolve({ reply: "done", sources: [] }) });
        });
      })
    );
    renderChat();
    await sendMessage("hello");
    expect(screen.getByText("Orbit is thinking…")).toBeInTheDocument();
    resolveRequest();
    expect(await screen.findByText("done")).toBeInTheDocument();
    expect(screen.queryByText("Orbit is thinking…")).not.toBeInTheDocument();
  });

  it("renders user text plainly and Orbit replies as markdown", async () => {
    mockFetch({ reply: "The syllabus covers **HV systems**." });
    renderChat();
    await sendMessage("What subjects?");
    expect(await screen.findByText("What subjects?")).toBeInTheDocument();
    expect(screen.getByText("HV systems").tagName).toBe("STRONG");
  });

  it("renders an API error message and retries the failed request", async () => {
    mockFetch({ status: "error", errorMessage: "Model quota exceeded" });
    renderChat();
    await sendMessage("hello");
    expect(await screen.findByText("Model quota exceeded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    mockFetch({ reply: "Retried successfully." });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Retried successfully.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("renders a backend-unreachable message on network failure", async () => {
    mockFetch({ networkError: true });
    renderChat();
    await sendMessage("hello");
    expect(await screen.findByText(/Couldn't reach the backend/)).toBeInTheDocument();
  });

  it("clears the conversation back to the empty state", async () => {
    mockFetch({ reply: "a reply" });
    renderChat();
    await sendMessage("hello");
    await screen.findByText("a reply");
    await userEvent.click(screen.getByRole("button", { name: "Clear Chat" }));
    expect(screen.getByText(/Good (morning|afternoon|evening)/)).toBeInTheDocument();
    expect(screen.queryByText("a reply")).not.toBeInTheDocument();
    expect(screen.queryByText("hello")).not.toBeInTheDocument();
  });

  it("renders a task-created action card with navigation", async () => {
    mockFetch({ reply: 'Created task "Wiring diagram" in project ID 2.' });
    renderChat();
    await sendMessage("create a wiring task");
    const card = await screen.findByRole("group", { name: "Task created" });
    expect(within(card).getByText("Wiring diagram")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Tasks" }));
    expect(await screen.findByText("TASKS PAGE")).toBeInTheDocument();
  });

  it("keeps action cards presentation-only (no mutation fired on navigation)", async () => {
    mockFetch({ reply: 'Created task "Wiring diagram".' });
    renderChat();
    await sendMessage("create a wiring task");
    await screen.findByRole("group", { name: "Task created" });
    const callsBefore = fetchPostCalls().length;
    await userEvent.click(screen.getByRole("button", { name: "Open Tasks" }));
    expect(await screen.findByText("TASKS PAGE")).toBeInTheDocument();
    expect(fetchPostCalls()).toHaveLength(callsBefore);
  });

  it("renders task updated, completed and deleted action cards", async () => {
    mockFetch({ reply: "Updated task 5." });
    renderChat();
    await sendMessage("update task 5");
    expect(await screen.findByRole("group", { name: "Task updated" })).toBeInTheDocument();

    mockFetch({ reply: "Marked task 4 as completed." });
    await userEvent.type(screen.getByLabelText("Message Orbit"), "complete task 4");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("group", { name: "Task completed" })).toBeInTheDocument();

    mockFetch({ reply: "Deleted task 3." });
    await userEvent.type(screen.getByLabelText("Message Orbit"), "delete task 3");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("group", { name: "Task deleted" })).toBeInTheDocument();
  });

  it("renders a calendar-event action card and navigates to the calendar", async () => {
    mockFetch({ reply: 'Created calendar event "HW review" starting at 2026-08-21T15:00:00+05:30.' });
    renderChat();
    await sendMessage("add an event");
    expect(await screen.findByRole("group", { name: "Calendar event created" })).toBeInTheDocument();
    expect(screen.getByText("HW review")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show Calendar" }));
    expect(await screen.findByText("CALENDAR PAGE")).toBeInTheDocument();
  });

  it("renders a day-plan scheduled action card with its blocks", async () => {
    mockFetch({
      reply:
        "Added these blocks to your Google Calendar:\n  10:00-10:45  Submit lab manual\n  11:00-12:00  Wiring check",
    });
    renderChat();
    await sendMessage("schedule the plan");
    const card = await screen.findByRole("group", { name: "Day plan scheduled" });
    expect(within(card).getByText("2 blocks added to Google Calendar")).toBeInTheDocument();
    expect(within(card).getByText("Submit lab manual")).toBeInTheDocument();
    expect(within(card).getByText("Wiring check")).toBeInTheDocument();
  });

  it("offers a confirmation that schedules the recommended plan via a chat request", async () => {
    mockFetch({
      reply:
        "Recommended schedule for 2026-08-20 (IST) — recommendation only, nothing was written to your calendar.\nScheduled:\n  10:00-10:45  Submit lab manual  [45m]\nSummary: 1 scheduled, 1 unscheduled, 45m planned, 120m unused.",
    });
    renderChat();
    await sendMessage("plan my day");
    expect(await screen.findByRole("group", { name: "Day plan ready" })).toBeInTheDocument();

    mockFetch({ reply: "Scheduled." });
    await userEvent.click(screen.getByRole("button", { name: "Schedule this plan" }));
    expect(await screen.findByText("Scheduled.")).toBeInTheDocument();
    const last = fetchPostCalls().pop();
    const body = JSON.parse(last[1].body);
    expect(body.messages).toContainEqual({
      role: "user",
      content: "Schedule the recommended plan.",
    });
  });

  it("renders unknown assistant text as normal markdown without a card", async () => {
    mockFetch({ reply: "You have 3 overdue tasks this week." });
    renderChat();
    await sendMessage("what's overdue?");
    expect(await screen.findByText("You have 3 overdue tasks this week.")).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("shows task, calendar and document context from real data", async () => {
    renderChat();
    expect(await screen.findByText("2 open tasks")).toBeInTheDocument();
    expect(screen.getByText("Connected to Google Calendar")).toBeInTheDocument();
    expect(screen.getByText("1 document")).toBeInTheDocument();
  });

  it("navigates to a project's Orbit AI from the context panel", async () => {
    renderChat();
    await screen.findByText("In-SEM");
    await userEvent.click(screen.getByRole("button", { name: "In-SEM" }));
    expect(await screen.findByText("PROJECT AI PAGE")).toBeInTheDocument();
  });

  it("persists conversation history in sessionStorage", async () => {
    mockFetch({ reply: "a reply" });
    const { unmount } = renderChat();
    await sendMessage("hello");
    await screen.findByText("a reply");
    const stored = JSON.parse(sessionStorage.getItem("ecc_chat_messages"));
    expect(stored.some((m) => m.role === "user" && m.content === "hello")).toBe(true);
    expect(stored.some((m) => m.role === "assistant" && m.content === "a reply")).toBe(true);

    unmount();
    mockFetch({ reply: "new" });
    renderChat();
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("a reply")).toBeInTheDocument();
    expect(screen.queryByText(/Good (morning|afternoon|evening)/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("2 open tasks")).toBeInTheDocument());
  });

  it("restores a Calendar-prefilled conversation", async () => {
    const prefill =
      "I've reviewed today's plan in the Calendar workspace. Please apply today's day plan to my Google Calendar and schedule the planned blocks.";
    sessionStorage.setItem(
      "ecc_chat_messages",
      JSON.stringify([{ role: "user", content: prefill }])
    );
    renderChat();
    expect(screen.getByText(prefill)).toBeInTheDocument();
    expect(screen.queryByText(/Good (morning|afternoon|evening)/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("2 open tasks")).toBeInTheDocument());
  });

  it("shows a document context indicator from the reply", async () => {
    mockFetch({
      reply: "The syllabus covers HV systems.\n\nSources: BE SEM 1 Syllabus.pdf",
    });
    renderChat();
    await sendMessage("What's in the syllabus?");
    const panel = await screen.findByLabelText("Referenced files");
    expect(panel.textContent).toContain("BE SEM 1 Syllabus.pdf");
  });

  it("shows an image context indicator from the reply", async () => {
    mockFetch({ reply: "The layout is shown in inverter_board.png." });
    renderChat();
    await sendMessage("what's in the screenshot?");
    const panel = await screen.findByLabelText("Referenced files");
    expect(panel.textContent).toContain("inverter_board.png");
  });

  it("restores focus to the context toggle after closing with Escape", async () => {
    const user = userEvent.setup();
    renderChat();
    const toggle = screen.getByRole("button", { name: "Context" });
    await user.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    await user.keyboard("{Escape}");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
  });

  it("keeps a responsive-safe structure with a live conversation region and context panel", async () => {
    renderChat();
    expect(screen.getByRole("log")).toBeInTheDocument();
    expect(screen.getByLabelText("Context")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Context" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear Chat" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("2 open tasks")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("AI online")).toBeInTheDocument());
  });
});
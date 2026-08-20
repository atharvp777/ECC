import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectAi from "./ProjectAi";

const PROJ_A = { id: 3, name: "In-SEM" };
const PROJ_B = { id: 4, name: "dMAT" };
const STORAGE_A = "ecc_project_chat_3";
const STORAGE_B = "ecc_project_chat_4";

function mockFetch({ reply = "backend reply" } = {}) {
  const mock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve({ reply, sources: [] }),
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function chatCalls() {
  return fetch.mock.calls.filter(([url]) => String(url).endsWith("/api/chat/"));
}

async function sendText(text) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Project AI message"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("ProjectAi — project-scoped session persistence", () => {
  it("starts empty when no stored conversation exists", () => {
    render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByLabelText("Example prompts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Summarize this project." })).toBeInTheDocument();
  });

  it("writes messages to the project-specific sessionStorage key", async () => {
    mockFetch({ reply: "schedule summary" });
    render(<ProjectAi project={PROJ_A} />);
    await sendText("What is my complete exam schedule?");
    await screen.findByText("schedule summary");

    const stored = JSON.parse(sessionStorage.getItem(STORAGE_A));
    expect(stored.some((m) => m.role === "user" && m.content === "What is my complete exam schedule?")).toBe(true);
    expect(stored.some((m) => m.role === "assistant" && m.content === "schedule summary")).toBe(true);
    expect(sessionStorage.getItem("ecc_chat_messages")).toBeNull();
    expect(sessionStorage.getItem(STORAGE_B)).toBeNull();
  });

  it("restores the conversation after unmount/remount", async () => {
    mockFetch({ reply: "schedule summary" });
    const { unmount } = render(<ProjectAi project={PROJ_A} />);
    await sendText("What is my complete exam schedule?");
    await screen.findByText("schedule summary");

    unmount();
    render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByText("What is my complete exam schedule?")).toBeInTheDocument();
    expect(screen.getByText("schedule summary")).toBeInTheDocument();
  });

  it("does not show project A's conversation in project B", async () => {
    const { unmount } = render(<ProjectAi project={PROJ_A} />);
    await sendText("question for A");
    await screen.findByText("backend reply");

    unmount();
    render(<ProjectAi project={PROJ_B} />);
    expect(screen.queryByText("question for A")).not.toBeInTheDocument();
    expect(screen.queryByText("backend reply")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Example prompts")).toBeInTheDocument();
  });

  it("restores project A when switching back from project B", async () => {
    const { unmount: unmountA } = render(<ProjectAi project={PROJ_A} />);
    await sendText("A question");
    await screen.findByText("backend reply");

    unmountA();
    const { unmount: unmountB } = render(<ProjectAi project={PROJ_B} />);
    await sendText("B question");
    await waitFor(() => expect(screen.getAllByText("backend reply")).toHaveLength(1));

    unmountB();
    render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByText("A question")).toBeInTheDocument();
    expect(screen.queryByText("B question")).not.toBeInTheDocument();
  });

  it("falls back to an empty conversation for corrupt stored data", () => {
    sessionStorage.setItem(STORAGE_A, "{not valid json!!");
    const first = render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByLabelText("Example prompts")).toBeInTheDocument();
    first.unmount();
  });

  it("falls back to an empty conversation for invalid (non-array) stored data", () => {
    sessionStorage.setItem(STORAGE_B, JSON.stringify({ role: "user", content: "not an array" }));
    const second = render(<ProjectAi project={PROJ_B} />);
    expect(screen.getByLabelText("Example prompts")).toBeInTheDocument();
    second.unmount();
  });

  it("does not trigger an API request when restoring a conversation", async () => {
    sessionStorage.setItem(
      STORAGE_A,
      JSON.stringify([
        { role: "user", content: "Q" },
        { role: "assistant", content: "A" },
      ])
    );
    const fetchMock = mockFetch();
    render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByText("Q")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });

  it("sends the project_id on new messages", async () => {
    mockFetch({ reply: "ok" });
    render(<ProjectAi project={PROJ_A} />);
    await sendText("hello");
    await screen.findByText("ok");

    const last = chatCalls().pop();
    const body = JSON.parse(last[1].body);
    expect(body.project_id).toBe(3);
    expect(body.messages[0].role).toBe("user");
    expect(body.messages[body.messages.length - 1]).toEqual({ role: "user", content: "hello" });
  });

  it("keeps the contextual-reference conversation intact across remounts", async () => {
    const reply1 = "Your exam schedule is 25-08, 27-08, 29-08.";
    mockFetch({ reply: reply1 });
    const { unmount } = render(<ProjectAi project={PROJ_A} />);
    await sendText("What is my complete exam schedule?");
    await screen.findByText(reply1);

    unmount();
    mockFetch({ reply: "I found these 3 dates..." });
    render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByText(reply1)).toBeInTheDocument();
    await sendText("Add those dates to my calendar");
    await screen.findByText("I found these 3 dates...");

    const last = chatCalls().pop();
    const body = JSON.parse(last[1].body);
    expect(body.project_id).toBe(3);
    expect(body.messages[1]).toEqual({ role: "user", content: "What is my complete exam schedule?" });
    expect(body.messages[2]).toEqual({ role: "assistant", content: reply1 });
    expect(body.messages[3]).toEqual({ role: "user", content: "Add those dates to my calendar" });
  });

  it("renders and sends messages exactly as before", async () => {
    mockFetch({ reply: "reply text" });
    render(<ProjectAi project={PROJ_A} />);
    expect(screen.getByText("Orbit AI")).toBeInTheDocument();

    await sendText("summarize");
    expect(await screen.findByText("summarize")).toBeInTheDocument();
    expect(await screen.findByText("reply text")).toBeInTheDocument();
    expect(screen.queryByLabelText("Example prompts")).not.toBeInTheDocument();
  });
});
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Sparkles, Send } from "lucide-react";
import OrbitButton from "./ui/OrbitButton";
import { formatAssistantContent } from "../utils/chatFormatting";
import { API_BASE_URL } from "../config";

const EXAMPLE_PROMPTS = [
  "What should I work on next?",
  "Summarize this project.",
  "What documents do I have?",
  "What's overdue?",
];

/**
 * Project-scoped Orbit AI. Reuses the existing /chat endpoint — a leading
 * context message scopes the conversation to this project. Not a second AI
 * implementation; the global Chat page remains canonical.
 */
export default function ProjectAi({ project }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    setMessages([]);
    setInput("");
  }, [project?.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, loading]);

  const send = async (text) => {
    const prompt = (text ?? input).trim();
    if (!prompt || loading) return;
    setInput("");
    const context = `This conversation is scoped to the project "${project?.name || "this project"}" (id ${project?.id}). Answer questions about this project using the user's projects, tasks, notes, and documents.`;
    const history = messages.filter((m) => m.role === "user" || m.role === "assistant");
    const next = [...history, { role: "user", content: prompt }];
    setMessages(next);
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/chat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [{ role: "user", content: context }, ...next],
        }),
      });
      const contentType = response.headers.get("content-type") || "";
      const data = contentType.includes("application/json")
        ? await response.json()
        : { reply: await response.text() };
      const reply = data.reply || data.detail || "Something went wrong. Please try again.";
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Couldn't reach the backend. Make sure it's running, then try again.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="project-ai">
      <div className="project-ai__header">
        <div className="project-ai__title">
          <Sparkles size={15} className="project-ai__mark" aria-hidden="true" />
          Orbit AI
        </div>
        <p className="project-ai__subtitle">Ask anything about this project.</p>
      </div>

      {messages.length === 0 && (
        <div className="project-ai__prompts" aria-label="Example prompts">
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button key={prompt} type="button" className="project-ai__prompt" onClick={() => send(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
      )}

      <div className="project-ai__stream">
        {messages.map((msg, idx) => (
          <div key={idx} className={`project-ai__row project-ai__row--${msg.role}`}>
            <div className={`project-ai__bubble project-ai__bubble--${msg.role}`}>
              {msg.role === "assistant" ? (
                <div className="chat-markdown">
                  <ReactMarkdown>{formatAssistantContent(msg.content)}</ReactMarkdown>
                </div>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}
        {loading && <div className="project-ai__bubble project-ai__bubble--assistant">Thinking…</div>}
        <div ref={endRef} />
      </div>

      <form
        className="project-ai__composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          className="project-ai__input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this project…"
          aria-label="Project AI message"
          disabled={loading}
        />
        <OrbitButton type="submit" variant="primary" disabled={loading || !input.trim()}>
          <Send size={13} aria-hidden="true" /> Send
        </OrbitButton>
      </form>
    </div>
  );
}
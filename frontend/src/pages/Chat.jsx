import { useState, useRef, useEffect } from "react";
import api from "../api/client";
import { Send, Bot, User, Sparkles, Trash2 } from "lucide-react";

const SUGGESTIONS = [
  "What's overdue right now?",
  "What should I focus on today?",
  "Summarize my active projects",
  "What meetings have open action items?",
  "What are my critical tasks?",
];

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{
      display: "flex", gap: 12, padding: "12px 0",
      flexDirection: isUser ? "row-reverse" : "row",
      alignItems: "flex-start",
    }}>
      {/* Avatar */}
      <div style={{
        width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
        background: isUser ? "var(--accent)" : "var(--surface2)",
        border: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {isUser ? <User size={14} color="#fff" /> : <Bot size={14} color="var(--accent)" />}
      </div>

      {/* Bubble */}
      <div style={{
        maxWidth: "72%",
        background: isUser ? "var(--accent)" : "var(--surface2)",
        border: `1px solid ${isUser ? "transparent" : "var(--border)"}`,
        borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
        padding: "10px 14px",
        fontSize: 13,
        lineHeight: 1.65,
        color: isUser ? "#fff" : "var(--text)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}>
        {msg.content}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: "flex", gap: 12, padding: "12px 0", alignItems: "flex-start" }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%",
        background: "var(--surface2)", border: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
      }}>
        <Bot size={14} color="var(--accent)" />
      </div>
      <div style={{
        background: "var(--surface2)", border: "1px solid var(--border)",
        borderRadius: "4px 16px 16px 16px", padding: "12px 16px",
        display: "flex", gap: 4, alignItems: "center",
      }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 6, height: 6, borderRadius: "50%", background: "var(--muted)",
            animation: "bounce 1.2s ease-in-out infinite",
            animationDelay: `${i * 0.2}s`,
          }} />
        ))}
      </div>
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: .4; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Hey Atharv 👋 I'm your Engineering Command Center AI.\n\nI have live access to your projects, tasks, notes, and meetings. Ask me anything — deadlines, priorities, what to focus on, or engineering questions.\n\nWhat's on your mind?",
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef();
  const inputRef  = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text) => {
    const userMsg = text || input.trim();
    if (!userMsg || loading) return;
    setInput("");

    const newMessages = [...messages, { role: "user", content: userMsg }];
    setMessages(newMessages);
    setLoading(true);

    try {
      const { data } = await api.post("/chat/", { messages: newMessages });
      setMessages(m => [...m, { role: "assistant", content: data.reply }]);
    } catch (err) {
      const errMsg = err.response?.status === 500
        ? "Backend error. Make sure the backend is running and your OpenAI key is set."
        : "Couldn't reach the backend. Is it running?";
      setMessages(m => [...m, { role: "assistant", content: `⚠ ${errMsg}` }]);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const clearChat = () => {
    setMessages([{
      role: "assistant",
      content: "Chat cleared. What do you need?",
    }]);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        padding: "12px 24px", borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
        background: "var(--surface)",
      }}>
        <Sparkles size={16} color="var(--accent)" />
        <span style={{ fontWeight: 600, fontSize: 13 }}>AI Assistant</span>
        <span style={{ fontSize: 11, color: "var(--muted)", flex: 1 }}>GPT-4o · live project context</span>
        <button className="btn btn-ghost btn-sm" onClick={clearChat} title="Clear chat">
          <Trash2 size={12} />
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 24px" }}>
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        {loading && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions — only on first message */}
      {messages.length === 1 && (
        <div style={{ padding: "0 24px 12px", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {SUGGESTIONS.map(s => (
            <button key={s} className="btn btn-ghost btn-sm"
              style={{ fontSize: 12, borderRadius: 20 }}
              onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div style={{
        padding: "12px 24px 16px", borderTop: "1px solid var(--border)",
        background: "var(--surface)", flexShrink: 0,
      }}>
        <div style={{
          display: "flex", gap: 10, background: "var(--surface2)",
          border: "1px solid var(--border)", borderRadius: 12, padding: "8px 8px 8px 14px",
          transition: "border-color .15s",
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask anything… (Enter to send, Shift+Enter for new line)"
            rows={1}
            style={{
              flex: 1, background: "none", border: "none", outline: "none",
              color: "var(--text)", font: "inherit", fontSize: 13, resize: "none",
              lineHeight: 1.5, maxHeight: 120, overflowY: "auto",
            }}
            onInput={e => {
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
            }}
          />
          <button
            className="btn btn-primary"
            style={{ borderRadius: 8, padding: "6px 12px", flexShrink: 0, alignSelf: "flex-end" }}
            onClick={() => send()}
            disabled={loading || !input.trim()}
          >
            <Send size={14} />
          </button>
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6, textAlign: "center" }}>
          Context: your live tasks, projects, notes & meetings are injected automatically
        </div>
      </div>
    </div>
  );
}

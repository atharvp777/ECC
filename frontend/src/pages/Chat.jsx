import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { formatAssistantContent } from "../utils/chatFormatting";

const CHAT_STORAGE_KEY = "ecc_chat_messages";

export default function Chat() {
  const initialMessage = {
    role: "assistant",
    content:
      "Hey Atharv 👋 I'm your Engineering Command Center AI.\n\nI have live access to your projects, tasks, notes, and meetings.",
  };
  const [messages, setMessages] = useState(() => {
    try {
      const stored = sessionStorage.getItem(CHAT_STORAGE_KEY);
      if (!stored) return [initialMessage];

      const parsed = JSON.parse(stored);
      if (!Array.isArray(parsed) || parsed.length === 0) return [initialMessage];

      const sanitized = parsed.filter(
        (message) =>
          message &&
          typeof message === "object" &&
          (message.role === "user" || message.role === "assistant") &&
          typeof message.content === "string"
      );

      return sanitized.length > 0 ? sanitized : [initialMessage];
    } catch {
      return [initialMessage];
    }
  });
const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [modelIndicator, setModelIndicator] = useState("Loading AI model…");
  const messagesEndRef = useRef(null);
  const contextInfo = "Live project context loaded";

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/chat/status")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.display) setModelIndicator(data.display);
      })
      .catch(() => setModelIndicator("AI model unavailable"));
  }, []);

  const styles = {
    shell: {
      display: "flex",
      flexDirection: "column",
      minHeight: "calc(100vh - 100px)",
      height: "100%",
      padding: 18,
      gap: 12,
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: 12,
    },
    header: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: 16,
      flexShrink: 0,
    },
    headerRight: {
      display: "flex",
      flexDirection: "column",
      alignItems: "flex-end",
      gap: 8,
      flexShrink: 0,
    },
    headerCopy: {
      display: "flex",
      flexDirection: "column",
      gap: 6,
      minWidth: 0,
    },
    titleRow: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      minWidth: 0,
    },
    title: {
      fontSize: 16,
      fontWeight: 700,
      lineHeight: 1.2,
      letterSpacing: "-0.01em",
    },
    onlinePill: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: "4px 10px",
      borderRadius: 999,
      border: "1px solid rgba(34, 197, 94, 0.25)",
      background: "rgba(34, 197, 94, 0.08)",
      color: "#9ef0bc",
      fontSize: 11,
      fontWeight: 600,
      whiteSpace: "nowrap",
    },
    onlineDot: {
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: "var(--success)",
      boxShadow: "0 0 0 3px rgba(34, 197, 94, 0.12)",
      flexShrink: 0,
    },
    metaLine: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8,
      alignItems: "center",
    },
    metaItem: {
      display: "inline-flex",
      alignItems: "center",
      padding: "4px 10px",
      borderRadius: 999,
      background: "rgba(100, 116, 139, 0.12)",
      border: "1px solid var(--border)",
      color: "var(--muted)",
      fontSize: 11,
      fontWeight: 600,
      whiteSpace: "nowrap",
    },
    metaAccent: {
      background: "rgba(79, 124, 255, 0.14)",
      color: "#9db7ff",
      borderColor: "rgba(79, 124, 255, 0.18)",
    },
    clearButton: {
      background: "transparent",
      border: "none",
      boxShadow: "none",
      color: "var(--muted)",
      padding: "6px 8px",
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 600,
      lineHeight: 1,
      alignSelf: "flex-end",
      flexShrink: 0,
    },
    stream: {
      flex: 1,
      minHeight: 0,
      overflowY: "auto",
      display: "flex",
      flexDirection: "column",
      gap: 12,
      padding: "4px 2px 10px",
      scrollbarGutter: "stable",
    },
    row: {
      display: "flex",
      alignItems: "flex-end",
      gap: 10,
    },
    rowUser: {
      justifyContent: "flex-end",
    },
    avatar: {
      width: 28,
      height: 28,
      borderRadius: 999,
      display: "grid",
      placeItems: "center",
      background: "rgba(79, 124, 255, 0.16)",
      border: "1px solid rgba(79, 124, 255, 0.28)",
      color: "#9db7ff",
      fontSize: 10,
      fontWeight: 800,
      letterSpacing: "0.05em",
      flexShrink: 0,
    },
    bubble: {
      maxWidth: "78%",
      padding: "12px 14px",
      borderRadius: 16,
      border: "1px solid transparent",
      wordBreak: "break-word",
      lineHeight: 1.55,
      fontSize: 13,
    },
    bubbleAssistant: {
      background: "var(--surface2)",
      borderColor: "var(--border)",
      color: "var(--text)",
      borderTopLeftRadius: 8,
    },
    bubbleUser: {
      background: "rgba(79, 124, 255, 0.14)",
      borderColor: "rgba(79, 124, 255, 0.18)",
      color: "#eff4ff",
      borderTopRightRadius: 8,
      whiteSpace: "pre-wrap",
    },
    composer: {
      position: "sticky",
      bottom: 0,
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: 12,
      borderRadius: 16,
      background: "rgba(20, 23, 32, 0.96)",
      border: "1px solid var(--border)",
      boxShadow: "0 10px 30px rgba(0, 0, 0, 0.22)",
    },
    input: {
      flex: 1,
      minWidth: 0,
      height: 46,
      borderRadius: 12,
      border: "1px solid var(--border)",
      background: "var(--surface2)",
      color: "var(--text)",
      boxShadow: "none",
      padding: "0 14px",
      outline: "none",
      fontSize: 13,
    },
    sendButton: {
      minWidth: 88,
      height: 46,
      borderRadius: 12,
      boxShadow: "none",
      justifyContent: "center",
    },
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // Ignore storage failures and keep chat functional.
    }
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  const send = async () => {
    const userMsg = input.trim();
    if (!userMsg || loading) return;
    setInput("");
    const newMessages = [...messages, { role: "user", content: userMsg }];
    setMessages(newMessages);
    setLoading(true);
    try {
      const response = await fetch("http://127.0.0.1:8000/api/chat/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: newMessages }),
      });
      const contentType = response.headers.get("content-type") || "";
      const data = contentType.includes("application/json")
        ? await response.json()
        : { reply: await response.text() };

      if (!response.ok) {
        const errorMessage = data.detail || data.reply || data.error || `Request failed (${response.status})`;
        setMessages((prev) => [...prev, { role: "assistant", content: errorMessage }]);
        setLoading(false);
        scrollToBottom();
        return;
      }

      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      setLoading(false);
      scrollToBottom();
    } catch (err) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, something went wrong." },
      ]);
      setLoading(false);
    }
  };

  const clearChat = () => {
    try {
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
    } catch {
      // Ignore storage failures and reset local state.
    }
    setMessages([initialMessage]);
  };

  return (
    <div className="chat-page" style={styles.shell}>
      <div style={styles.header}>
        <div style={styles.headerCopy}>
          <div style={styles.titleRow}>
            <h2 style={styles.title}>AI Chat</h2>
          </div>
          <div style={styles.metaLine}>
            <span style={styles.metaItem}>{modelIndicator}</span>
            <span style={{ ...styles.metaItem, ...styles.metaAccent }}>{contextInfo}</span>
          </div>
        </div>

        <div style={styles.headerRight}>
          <div style={styles.onlinePill} title="Connected">
            <span style={styles.onlineDot} />
            Online
          </div>
          <button style={styles.clearButton} type="button" onClick={clearChat}>
            Clear Chat
          </button>
        </div>
      </div>

      <div style={styles.stream}>
        {messages.map((msg, idx) => (
          <div
            key={idx}
            style={{
              ...styles.row,
              ...(msg.role === "user" ? styles.rowUser : null),
            }}
          >
            {msg.role === "assistant" && (
              <div style={styles.avatar} aria-hidden="true">
                AI
              </div>
            )}
            <div
              style={{
                ...styles.bubble,
                ...(msg.role === "user" ? styles.bubbleUser : styles.bubbleAssistant),
              }}
            >
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
        <div ref={messagesEndRef} />
      </div>

      <form
        style={styles.composer}
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          style={styles.input}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          disabled={loading}
          aria-label="Message input"
        />
        <button
          className="btn btn-primary"
          style={styles.sendButton}
          type="submit"
          disabled={loading || !input.trim()}
        >
          {loading ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}

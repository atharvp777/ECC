import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../config";
import { getProjects, getTasks, getDocuments, getIntegrationStatus } from "../api";
import ChatEmptyState from "../components/chat/ChatEmptyState";
import ChatMessageList from "../components/chat/ChatMessageList";
import ChatComposer from "../components/chat/ChatComposer";
import ChatContextPanel from "../components/chat/ChatContextPanel";

const CHAT_STORAGE_KEY = "ecc_chat_messages";

function loadInitialMessages() {
  try {
    const stored = sessionStorage.getItem(CHAT_STORAGE_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (message) =>
        message &&
        typeof message === "object" &&
        (message.role === "user" || message.role === "assistant") &&
        typeof message.content === "string"
    );
  } catch {
    return [];
  }
}

function postChat(convo) {
  return fetch(`${API_BASE_URL}/api/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: convo }),
  }).then(async (response) => {
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : { reply: await response.text() };
    return { ok: response.ok, status: response.status, data };
  });
}

function offlineMessage() {
  return window.navigator.onLine
    ? "Couldn't reach the backend. Make sure it's running, then try again."
    : "You're offline. Reconnect to send messages.";
}

export default function Chat() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState(loadInitialMessages);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastError, setLastError] = useState(null);
  const [aiStatus, setAiStatus] = useState("checking");
  const [contextOpen, setContextOpen] = useState(() => {
    try {
      return (
        typeof window.matchMedia === "function" &&
        window.matchMedia("(min-width: 900px)").matches
      );
    } catch {
      return false;
    }
  });
  const [context, setContext] = useState({
    loaded: false,
    projects: [],
    tasks: [],
    documents: [],
    calendarConnected: null,
  });

  const contextToggleRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/chat/status`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled) return;
        setAiStatus(data && data.configured ? "online" : "unavailable");
      })
      .catch(() => {
        if (!cancelled) setAiStatus("unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getProjects(), getTasks(), getDocuments(), getIntegrationStatus()])
      .then(([projects, tasks, documents, status]) => {
        if (cancelled) return;
        setContext({
          loaded: true,
          projects: Array.isArray(projects) ? projects : [],
          tasks: Array.isArray(tasks) ? tasks : [],
          documents: Array.isArray(documents) ? documents : [],
          calendarConnected: Boolean(status && status.google_calendar),
        });
      })
      .catch(() => {
        if (cancelled) return;
        setContext({
          loaded: true,
          projects: [],
          tasks: [],
          documents: [],
          calendarConnected: null,
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // Keep chat functional if storage is unavailable.
    }
  }, [messages]);

  useEffect(() => {
    if (!contextOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setContextOpen(false);
        contextToggleRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [contextOpen]);

  const send = async (override) => {
    const userMsg = (override ?? input).trim();
    if (!userMsg || loading) return;
    setInput("");
    setLastError(null);
    const next = [...messages, { role: "user", content: userMsg }];
    setMessages(next);
    setLoading(true);
    try {
      const { ok, data } = await postChat(next);
      if (!ok) {
        const errorMessage =
          data.detail || data.reply || data.error || `Request failed (${data.status || "error"})`;
        setMessages((prev) => [...prev, { role: "assistant", content: errorMessage }]);
        setLastError(userMsg);
        return;
      }
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: offlineMessage() },
      ]);
      setLastError(userMsg);
    } finally {
      setLoading(false);
    }
  };

  const retry = async () => {
    if (!lastError || loading) return;
    const convo = messages.slice(0, -1);
    setLoading(true);
    try {
      const { ok, data } = await postChat(convo);
      if (!ok) {
        const errorMessage =
          data.detail || data.reply || data.error || "Request failed";
        setMessages((prev) => [...prev, { role: "assistant", content: errorMessage }]);
        return;
      }
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      setLastError(null);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: offlineMessage() },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const clearChat = () => {
    try {
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
    } catch {
      // Reset local state regardless.
    }
    setMessages([]);
    setInput("");
    setLastError(null);
  };

  const confirmSchedule = () => {
    send("Schedule the recommended plan.");
  };

  const statusLabel =
    aiStatus === "online"
      ? "AI online"
      : aiStatus === "unavailable"
        ? "AI unavailable"
        : "Checking…";

  return (
    <div className="orbit-chat">
      <header className="orbit-chat__header">
        <div className="orbit-chat__heading">
          <h1 className="orbit-chat__title">
            <span className="orbit-chat__mark" aria-hidden="true">✦</span> Orbit AI
          </h1>
          <p className="orbit-chat__subtitle">Your intelligent engineering workspace.</p>
        </div>
        <div className="orbit-chat__header-actions">
          <span
            className={`orbit-chat__status orbit-chat__status--${aiStatus}`}
            role="status"
          >
            <span className="orbit-chat__status-dot" aria-hidden="true" />
            {statusLabel}
          </span>
          <button
            type="button"
            className="orbit-btn orbit-btn--secondary orbit-btn--sm orbit-chat__context-toggle"
            aria-expanded={contextOpen}
            aria-controls="orbit-chat-context"
            ref={contextToggleRef}
            onClick={() => setContextOpen((value) => !value)}
          >
            Context
          </button>
          <button
            type="button"
            className="orbit-btn orbit-btn--ghost orbit-btn--sm"
            onClick={clearChat}
          >
            Clear Chat
          </button>
        </div>
      </header>

      <div className="orbit-chat__layout">
        <div className="orbit-chat__main">
          <div
            className="orbit-chat__conversation"
            role="log"
            aria-live="polite"
            aria-busy={loading}
          >
            {messages.length === 0 ? (
              <ChatEmptyState onSuggestion={send} />
            ) : (
              <ChatMessageList
                messages={messages}
                loading={loading}
                onNavigate={navigate}
                onConfirm={confirmSchedule}
              />
            )}
          </div>

          {lastError && !loading && (
            <div className="orbit-chat__error" role="alert">
              <span className="orbit-chat__error-text">
                That message failed. You can retry.
              </span>
              <button
                type="button"
                className="orbit-btn orbit-btn--secondary orbit-btn--sm"
                onClick={retry}
              >
                Retry
              </button>
            </div>
          )}

          <ChatComposer
            value={input}
            onChange={setInput}
            onSend={send}
            loading={loading}
          />
        </div>

        <ChatContextPanel
          open={contextOpen}
          loading={!context.loaded}
          projects={context.projects}
          tasks={context.tasks}
          documents={context.documents}
          calendarConnected={context.calendarConnected}
          onNavigate={navigate}
          onOpenProject={(id) => navigate(`/projects/${id}/ai`)}
          onClose={() => {
            setContextOpen(false);
            contextToggleRef.current?.focus();
          }}
        />
      </div>

      {contextOpen && (
        <button
          type="button"
          className="orbit-chat__scrim"
          aria-label="Close context panel"
          onClick={() => {
            setContextOpen(false);
            contextToggleRef.current?.focus();
          }}
        />
      )}
    </div>
  );
}
import { useEffect, useRef } from "react";
import ChatMessage from "./ChatMessage";

export default function ChatMessageList({ messages, loading, onNavigate, onConfirm, dismissed, onDismiss }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  return (
    <div className="orbit-chat__message-list">
      {messages.map((message, index) => (
        <ChatMessage
          key={index}
          message={message}
          onNavigate={onNavigate}
          onConfirm={onConfirm}
          dismissed={dismissed}
          onDismiss={onDismiss}
        />
      ))}
      {loading && (
        <div className="orbit-chat__thinking" role="status">
          Orbit is thinking…
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
import React, { useState, useRef, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useNavigate } from "react-router-dom";

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hey Atharv 👋 I'm your Engineering Command Center AI.\n\nI have live access to your ",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef();

  // Model / context indicator (static for now)
  const modelIndicator = "llama-3.3-70b (Groq)";
  const contextInfo = "Live project context loaded";

  useEffect(() => {
    bottomRef.current = document.getElementById("bottom");
  }, []);

  const scrollToBottom = () => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
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
      const data = await response.json();
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
    setMessages([
      {
        role: "assistant",
        content:
          "Hey Atharv 👋 I'm your Engineering Command Center AI.\n\nI have live access to your ",
      },
    ]);
  };

  return (
    <div className="chat-container">
      {/* Header with model/context indicator and clear button */}
      <div className="header">
        <h2>AI Assistant</h2>
        <div className="indicator">
          <span>{modelIndicator}</span>
          <span>{contextInfo}</span>
        </div>
        <button onClick={clearChat}>Clear Chat</button>
      </div>

      <div className="messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
      </div>

      <div className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          disabled={loading}
          id="bottom"
          ref={bottomRef}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button onClick={send} disabled={loading || !input}>
          Send
        </button>
      </div>
    </div>
  );
}

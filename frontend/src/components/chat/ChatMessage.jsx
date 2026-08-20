import ReactMarkdown from "react-markdown";
import {
  formatAssistantContent,
  parseActionCard,
  extractContextIndicators,
} from "../../utils/chatFormatting";
import ChatActionCard from "./ChatActionCard";

function cardKeyOf(card) {
  return `${card.kind}:${card.title}`;
}

export default function ChatMessage({ message, onNavigate, onConfirm, dismissed, onDismiss }) {
  const isUser = message.role === "user";
  const card = isUser ? null : parseActionCard(message.content);
  const indicators = isUser ? [] : extractContextIndicators(message.content);
  const cardDismissed = card ? dismissed.has(cardKeyOf(card)) : false;

  return (
    <div
      className={`orbit-chat__message orbit-chat__message--${isUser ? "user" : "orbit"}`}
    >
      {isUser ? (
        <p className="orbit-chat__user-text">{message.content}</p>
      ) : (
        <div className="orbit-chat__orbit">
          {card && !cardDismissed && (
            <ChatActionCard
              card={card}
              onNavigate={onNavigate}
              onConfirm={onConfirm}
              onDismiss={onDismiss}
            />
          )}
          {indicators.length > 0 && (
            <div
              className="orbit-chat__indicators"
              aria-label="Referenced files"
            >
              {indicators.map((indicator) => (
                <span
                  key={indicator.name}
                  className="orbit-chat__indicator"
                  title={indicator.kind === "image" ? "Image" : "Document"}
                >
                  {indicator.kind === "image" ? "🖼️" : "📄"} {indicator.name}
                </span>
              ))}
            </div>
          )}
          <div className="chat-markdown orbit-chat__body">
            <ReactMarkdown>
              {formatAssistantContent(message.content)}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
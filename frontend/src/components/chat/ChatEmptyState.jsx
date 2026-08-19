const SUGGESTIONS = [
  "Plan my day",
  "What's most important today?",
  "Create a task",
  "Summarize a project",
  "Search my knowledge",
  "Check my calendar",
];

function greetingForHour(hour) {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function ChatEmptyState({ onSuggestion }) {
  const greeting = greetingForHour(new Date().getHours());

  return (
    <div className="orbit-chat__empty">
      <h2 className="orbit-chat__greeting">
        {greeting}. What are we working on?
      </h2>
      <div className="orbit-chat__suggestions" role="group" aria-label="Suggested prompts">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            className="orbit-chat__suggestion"
            onClick={() => onSuggestion(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
export default function ChatComposer({ value, onChange, onSend, loading }) {
  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  };

  return (
    <form
      className="orbit-chat__composer"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <textarea
        className="orbit-chat__input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Message Orbit…"
        aria-label="Message Orbit"
        disabled={loading}
        rows={1}
      />
      <button
        className="orbit-btn orbit-btn--primary orbit-chat__send"
        type="submit"
        disabled={loading || !value.trim()}
      >
        {loading ? "Thinking…" : "Send"}
      </button>
    </form>
  );
}
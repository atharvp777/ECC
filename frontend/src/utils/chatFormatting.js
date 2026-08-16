function escapeMarkdown(text) {
  return String(text).replace(/[\\`*_{}\[\]()#+\-.!>]/g, "\\$&");
}

function splitListBody(body) {
  const normalized = String(body ?? "").trim();
  if (!normalized) return [];

  if (normalized.includes(";")) {
    return normalized
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  return normalized
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parsePriorityItem(item) {
  const match = String(item).trim().match(/^\[(LOW|MEDIUM|HIGH|CRITICAL)\]\s*(.+)$/i);
  if (!match) {
    return {
      name: String(item).trim(),
      priority: null,
    };
  }

  return {
    name: match[2].trim(),
    priority: match[1].toUpperCase(),
  };
}

function formatItemsAsMarkdown(items, { showPriority = false } = {}) {
  return items
    .map((item) => {
      const parsed = parsePriorityItem(item);

      if (showPriority && parsed.priority) {
        return `- ${escapeMarkdown(parsed.name)} — **${parsed.priority}**`;
      }

      return `- ${escapeMarkdown(parsed.name || item)}`;
    })
    .join("\n");
}

export function formatAssistantContent(content) {
  const text = String(content ?? "").trim();

  if (!text) {
    return "I didn't get a response.";
  }

  const toolErrorMatch = text.match(/^Tool '(.+?)' failed:\s*(.+)$/s);
  if (toolErrorMatch) {
    const detail = toolErrorMatch[2].trim();

    const missingProjectMatch = detail.match(/^Project not found:\s*"?(.+?)"?$/i);
    if (missingProjectMatch) {
      return `I couldn't find a project named \`${escapeMarkdown(missingProjectMatch[1])}\`. Please check the project name and try again.`;
    }

    const ambiguousProjectMatch = detail.match(/^Ambiguous project name:\s*"?(.+?)"?$/i);
    if (ambiguousProjectMatch) {
      return `I found more than one project matching \`${escapeMarkdown(ambiguousProjectMatch[1])}\`. Please use the exact project name.`;
    }

    if (/no result was returned/i.test(detail)) {
      return "That action didn't return a result. Please try again.";
    }

    return detail;
  }

  const createdTaskMatch = text.match(/^Created task "(.+?)"(?: in project ID \d+)?\.$/s);
  if (createdTaskMatch) {
    return `Task created successfully: **${escapeMarkdown(createdTaskMatch[1])}**.`;
  }

  const createdProjectMatch = text.match(/^Created project "(.+?)"\.$/s);
  if (createdProjectMatch) {
    return `Project created successfully: **${escapeMarkdown(createdProjectMatch[1])}**.`;
  }

  const updatedProjectMatch = text.match(/^Updated project "(.+?)"\.$/s);
  if (updatedProjectMatch) {
    return `Project updated successfully: **${escapeMarkdown(updatedProjectMatch[1])}**.`;
  }

  if (/^Updated task \d+\.$/s.test(text)) {
    return "Task updated successfully.";
  }

  if (/^Marked task \d+ as completed\.$/s.test(text)) {
    return "Task marked as completed.";
  }

  const tasksMatch = text.match(/^Tasks:\s*(.*)$/is);
  if (tasksMatch) {
    const items = splitListBody(tasksMatch[1]);
    if (!items.length) {
      return "No tasks found.";
    }

    return `Tasks for today\n\n${formatItemsAsMarkdown(items, { showPriority: true })}`;
  }

  const projectsMatch = text.match(/^Projects:\s*(.*)$/is);
  if (projectsMatch) {
    const items = splitListBody(projectsMatch[1].replace(/,/g, ";"));
    if (!items.length) {
      return "No projects found.";
    }

    return `Projects\n\n${formatItemsAsMarkdown(items)}`;
  }

  const meetingsMatch = text.match(/^Meetings:\s*(.*)$/is);
  if (meetingsMatch) {
    const items = splitListBody(meetingsMatch[1]);
    if (!items.length) {
      return "No meetings found.";
    }

    return `Meetings\n\n${formatItemsAsMarkdown(items)}`;
  }

  const calendarMatch = text.match(/^Calendar events?:\s*(.*)$/is);
  if (calendarMatch) {
    const items = splitListBody(calendarMatch[1]);
    if (!items.length) {
      return "No upcoming events.";
    }

    return `Upcoming calendar events\n\n${formatItemsAsMarkdown(items)}`;
  }

  return text;
}

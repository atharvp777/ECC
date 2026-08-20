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

  // A [SAVE_CONTEXT] offer is a UI affordance, not prose: strip the marker so
  // the plain text answer reads cleanly (the suggest card renders the offer).
  const stripped = text.replace(/\[SAVE_CONTEXT\][\s\S]*?\[\/SAVE_CONTEXT\]/g, "").trim();
  const contentForDisplay = stripped || text;

  const toolErrorMatch = contentForDisplay.match(/^Tool '(.+?)' failed:\s*(.+)$/s);
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

  const createdTaskMatch = contentForDisplay.match(/^Created task "(.+?)"(?: in project ID \d+)?\.$/s);
  if (createdTaskMatch) {
    return `Task created successfully: **${escapeMarkdown(createdTaskMatch[1])}**.`;
  }

  const createdProjectMatch = contentForDisplay.match(/^Created project "(.+?)"\.$/s);
  if (createdProjectMatch) {
    return `Project created successfully: **${escapeMarkdown(createdProjectMatch[1])}**.`;
  }

  const updatedProjectMatch = contentForDisplay.match(/^Updated project "(.+?)"\.$/s);
  if (updatedProjectMatch) {
    return `Project updated successfully: **${escapeMarkdown(updatedProjectMatch[1])}**.`;
  }

  if (/^Updated task \d+\.$/s.test(contentForDisplay)) {
    return "Task updated successfully.";
  }

  if (/^Marked task \d+ as completed\.$/s.test(contentForDisplay)) {
    return "Task marked as completed.";
  }

  const tasksMatch = contentForDisplay.match(/^Tasks:\s*(.*)$/is);
  if (tasksMatch) {
    const items = splitListBody(tasksMatch[1]);
    if (!items.length) {
      return "No tasks found.";
    }

    return `Tasks for today\n\n${formatItemsAsMarkdown(items, { showPriority: true })}`;
  }

  const projectsMatch = contentForDisplay.match(/^Projects:\s*(.*)$/is);
  if (projectsMatch) {
    const items = splitListBody(projectsMatch[1].replace(/,/g, ";"));
    if (!items.length) {
      return "No projects found.";
    }

    return `Projects\n\n${formatItemsAsMarkdown(items)}`;
  }

  const meetingsMatch = contentForDisplay.match(/^Meetings:\s*(.*)$/is);
  if (meetingsMatch) {
    const items = splitListBody(meetingsMatch[1]);
    if (!items.length) {
      return "No meetings found.";
    }

    return `Meetings\n\n${formatItemsAsMarkdown(items)}`;
  }

  const calendarMatch = contentForDisplay.match(/^Calendar events?:\s*(.*)$/is);
  if (calendarMatch) {
    const items = splitListBody(calendarMatch[1]);
    if (!items.length) {
      return "No upcoming events.";
    }

    return `Upcoming calendar events\n\n${formatItemsAsMarkdown(items)}`;
  }

  // A saved-context confirmation's body reads as the fact itself; the card
  // already carries the project name / navigation, so show only the content.
  const savedContextMatch = contentForDisplay.match(
    /^Saved to ".+?" project context \(project \d+\):\s*\n?([\s\S]+)$/s
  );
  if (savedContextMatch) {
    return savedContextMatch[1].trim();
  }

  return contentForDisplay;
}

/* ============================================================================
   ACTION CARDS (presentation only)
   ----------------------------------------------------------------------------
   A card is produced ONLY when the assistant's reply confidently matches a
   known backend action/result pattern. Cards never execute mutations and never
   fabricate ids — they only summarize what the assistant text already claims
   and offer navigation/confirmation that reuse existing flows.
   ========================================================================== */

const DAY_PLAN_BLOCK_RE = /^\s*(\d{1,2}:\d{2})-(\d{1,2}:\d{2})\s+(.+?)(?:\s*\[(\d+)m\])?\s*$/gm;

function extractDayPlanBlocks(text) {
  const blocks = [];
  let m;
  DAY_PLAN_BLOCK_RE.lastIndex = 0;
  while ((m = DAY_PLAN_BLOCK_RE.exec(text)) !== null) {
    blocks.push({ start: m[1], end: m[2], title: m[3] });
    if (blocks.length >= 12) break;
  }
  return blocks;
}

export function parseActionCard(content) {
  const text = String(content ?? "").trim();
  if (!text) return null;

  let m;

  m = text.match(/^Created task "(.+?)" and added it to your Google Calendar\.$/);
  if (m) {
    return {
      kind: "task-created",
      title: m[1],
      meta: "Added to Google Calendar",
      nav: [{ label: "Open Tasks", to: "/tasks" }],
    };
  }
  m = text.match(/^Created task "(.+?)"(?: in project ID \d+)?\.$/);
  if (m) {
    return {
      kind: "task-created",
      title: m[1],
      nav: [{ label: "Open Tasks", to: "/tasks" }],
    };
  }

  m = text.match(/^Updated task "(.+?)" — estimate set to (\d+) minutes\.$/);
  if (m) {
    return {
      kind: "task-updated",
      title: m[1],
      meta: `Estimate set to ${m[2]} minutes`,
      nav: [{ label: "Open Tasks", to: "/tasks" }],
    };
  }
  m = text.match(/^Updated task (\d+)\.$/);
  if (m) {
    return {
      kind: "task-updated",
      title: `Task ${m[1]}`,
      nav: [{ label: "Open Tasks", to: "/tasks" }],
    };
  }

  m = text.match(/^Marked task (\d+) as completed\.$/);
  if (m) {
    return {
      kind: "task-completed",
      title: `Task ${m[1]}`,
      meta: "Completed",
      nav: [{ label: "Open Tasks", to: "/tasks" }],
    };
  }

  m = text.match(/^Deleted task (\d+)\.$/);
  if (m) {
    return {
      kind: "task-deleted",
      title: `Task ${m[1]}`,
      nav: [{ label: "Open Tasks", to: "/tasks" }],
    };
  }

  m = text.match(/^Created calendar event "(.+?)" starting at (.+?)\.$/);
  if (m) {
    return {
      kind: "calendar-event-created",
      title: m[1],
      meta: `Starts ${m[2]}`,
      nav: [{ label: "Show Calendar", to: "/calendar" }],
    };
  }

  m = text.match(/^Created project "(.+?)"\.$/);
  if (m) {
    return {
      kind: "project-created",
      title: m[1],
      nav: [{ label: "View Projects", to: "/projects" }],
    };
  }
  m = text.match(/^Updated project "(.+?)"\.$/);
  if (m) {
    return {
      kind: "project-updated",
      title: m[1],
      nav: [{ label: "View Projects", to: "/projects" }],
    };
  }

  if (text.includes("Added these blocks to your Google Calendar:")) {
    const blocks = extractDayPlanBlocks(text);
    return {
      kind: "day-plan-scheduled",
      title: "Day plan scheduled",
      meta:
        blocks.length > 0
          ? `${blocks.length} block${blocks.length === 1 ? "" : "s"} added to Google Calendar`
          : "Added to Google Calendar",
      blocks,
      nav: [{ label: "Show Calendar", to: "/calendar" }],
    };
  }

  if (/^Recommended schedule for \d{4}-\d{2}-\d{2}/.test(text)) {
    const blocks = extractDayPlanBlocks(text);
    return {
      kind: "day-plan-ready",
      title: "Day plan ready",
      meta: "Recommended schedule — nothing scheduled yet",
      blocks,
      nav: [{ label: "Show Calendar", to: "/calendar" }],
      confirm: "Schedule this plan",
    };
  }

  // A context fact was saved to a project's durable memory. The project id is
  // embedded in the reply so the card can navigate straight to that project's
  // Context tab. Presentation only — the write already happened server-side.
  m = text.match(
    /^Saved to "(.+?)" project context \(project (\d+)\):\s*\n?([\s\S]+)$/s
  );
  if (m) {
    return {
      kind: "context-saved",
      title: m[3].trim(),
      meta: `Saved to ${m[1]} project context`,
      nav: [{ label: "View project context", to: `/projects/${m[2]}/context` }],
    };
  }

  // The assistant OFFERED to save a durable fact. This is a suggestion only —
  // nothing is written until the user confirms via the card's action.
  m = text.match(/\[SAVE_CONTEXT\]([^:\]]+):\s*([\s\S]*?)\[\/SAVE_CONTEXT\]/);
  if (m) {
    return {
      kind: "context-suggest",
      title: "Save this as project context?",
      meta: `${m[1].trim()}`,
      blocks: [
        { start: "Fact", end: "", title: m[2].trim() },
      ],
      confirm: "Save to project context",
      dismiss: "Don't save",
    };
  }

  return null;
}

/* ============================================================================
   DOCUMENT / IMAGE CONTEXT INDICATORS
   ----------------------------------------------------------------------------
   Compact, honest chips derived ONLY from filenames that already appear in the
   assistant's reply text. No previews, no re-sent bytes, no invented files.
   ========================================================================== */

const FILE_REF_RE = /([A-Za-z0-9][A-Za-z0-9 ._\-\u2019']*?\.(pdf|png|jpe?g|webp|gif|docx?|xlsx?|pptx?|txt|csv|md))\b/gi;
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "gif"]);

export function extractContextIndicators(content) {
  const text = String(content ?? "");
  if (!text) return [];

  const found = [];
  const seen = new Set();
  let m;
  FILE_REF_RE.lastIndex = 0;
  while ((m = FILE_REF_RE.exec(text)) !== null) {
    const name = m[1].trim();
    if (name.length < 3 || name.length > 120 || seen.has(name)) continue;
    seen.add(name);
    const ext = m[2].toLowerCase();
    found.push({ name, kind: IMAGE_EXTENSIONS.has(ext) ? "image" : "document" });
    if (found.length >= 6) break;
  }
  return found;
}

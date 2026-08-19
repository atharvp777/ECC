export const CATEGORIES = [
  { value: "personal", label: "Personal" },
  { value: "baja", label: "Baja" },
  { value: "jobprep", label: "JobPrep" },
  { value: "college", label: "College" },
  { value: "studyabroad", label: "Study Abroad" },
];

export const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label]));

export const PROJECT_STATUSES = [
  { value: "active", label: "Active" },
  { value: "on_hold", label: "On hold" },
  { value: "completed", label: "Completed" },
  { value: "archived", label: "Archived" },
];

export const STATUS_LABELS = Object.fromEntries(PROJECT_STATUSES.map((s) => [s.value, s.label]));

export const STATUS_BADGE = {
  active: "success",
  on_hold: "warning",
  completed: "info",
  archived: "default",
};

export const PROJECT_COLORS = ["#4f7cff", "#7c3aed", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4"];

/** "Due Aug 24" or "Overdue · Aug 18". Returns null when there is no deadline. */
export function formatProjectDeadline(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const date = `${MONTHS[d.getMonth()]} ${d.getDate()}`;
  return d < new Date() ? `Overdue · ${date}` : `Due ${date}`;
}

/** Progress percentage (0–100) or null when there are no tasks. */
export function projectPercent(done, total) {
  if (!total) return null;
  return Math.round((done / total) * 100);
}
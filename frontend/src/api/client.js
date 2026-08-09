import axios from "axios";

const api = axios.create({
  baseURL: "http://127.0.0.1:8000",
  timeout: 10000,
});

export const getBackendHealth = () => api.get("/").then(response => response.data);

export default api;

// ── Dashboard ──────────────────────────────────────────────
export const getDashboardStats = () => api.get("/dashboard/stats").then(r => r.data);

// ── Projects ───────────────────────────────────────────────
export const getProjects      = ()       => api.get("/projects/").then(r => r.data);
export const getProject       = (id)     => api.get(`/projects/${id}`).then(r => r.data);
export const createProject    = (data)   => api.post("/projects/", data).then(r => r.data);
export const updateProject    = (id, d)  => api.patch(`/projects/${id}`, d).then(r => r.data);
export const deleteProject    = (id)     => api.delete(`/projects/${id}`);

// ── Tasks ──────────────────────────────────────────────────
export const getTasks         = (params) => api.get("/tasks/", { params }).then(r => r.data);
export const getTodayTasks    = ()       => api.get("/tasks/today").then(r => r.data);
export const getUpcomingTasks = (days=7) => api.get("/tasks/upcoming", { params: { days } }).then(r => r.data);
export const createTask       = (data)   => api.post("/tasks/", data).then(r => r.data);
export const updateTask       = (id, d)  => api.patch(`/tasks/${id}`, d).then(r => r.data);
export const deleteTask       = (id)     => api.delete(`/tasks/${id}`);

// ── Notes ──────────────────────────────────────────────────
export const getNotes         = (params) => api.get("/notes/", { params }).then(r => r.data);
export const createNote       = (data)   => api.post("/notes/", data).then(r => r.data);
export const updateNote       = (id, d)  => api.patch(`/notes/${id}`, d).then(r => r.data);
export const deleteNote       = (id)     => api.delete(`/notes/${id}`);

// ── Documents ──────────────────────────────────────────────
export const getDocuments     = (params) => api.get("/documents/", { params }).then(r => r.data);
export const deleteDocument   = (id)     => api.delete(`/documents/${id}`);
export const uploadDocument   = (formData) =>
  api.post("/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);

// ── Meetings ───────────────────────────────────────────────
export const getMeetings      = (params) => api.get("/meetings/", { params }).then(r => r.data);
export const getMeeting       = (id)     => api.get(`/meetings/${id}`).then(r => r.data);
export const createMeeting    = (data)   => api.post("/meetings/", data).then(r => r.data);
export const updateMeeting    = (id, d)  => api.patch(`/meetings/${id}`, d).then(r => r.data);
export const deleteMeeting    = (id)     => api.delete(`/meetings/${id}`);
export const updateActionItem = (mid, iid, d) =>
  api.patch(`/meetings/${mid}/action-items/${iid}`, d).then(r => r.data);

// ── Knowledge Base ─────────────────────────────────────────────────────────
export const searchDocs   = (query, top_k=5) => api.post("/knowledge/search", { query, top_k }).then(r => r.data);
export const askDocs      = (question)       => api.post("/knowledge/ask",    { question }).then(r => r.data);
export const ingestDoc    = (doc_id)         => api.post(`/knowledge/ingest/${doc_id}`).then(r => r.data);
export const indexStatus  = ()               => api.get("/knowledge/status").then(r => r.data);

// ── Integrations ────────────────────────────────────────────────────────────
export const getIntegrationStatus = ()           => api.get("/integrations/status").then(r => r.data);
export const getGoogleEvents       = (days=14)   => api.get("/integrations/google/events", { params: { days } }).then(r => r.data);
export const disconnectGoogle      = ()          => api.delete("/integrations/google/disconnect").then(r => r.data);
export const getGithubRepos        = ()          => api.get("/integrations/github/repos").then(r => r.data);
export const getGithubIssues       = (repo)      => api.get("/integrations/github/issues", { params: { repo } }).then(r => r.data);
export const getGithubPRs          = (repo)      => api.get("/integrations/github/prs", { params: { repo } }).then(r => r.data);
export const getGithubCommits      = (repo)      => api.get("/integrations/github/commits", { params: { repo } }).then(r => r.data);
export const pushTaskToGithub      = (payload)   => api.post("/integrations/github/push-task", payload).then(r => r.data);

// ── Meeting Intelligence ────────────────────────────────────────────────────
export const summarizeMeeting  = (id)        => api.post(`/meetings/intelligence/summarize/${id}`).then(r => r.data);
export const transcribeMeeting = (id, file)  => {
  const fd = new FormData(); fd.append("file", file);
  return api.post(`/meetings/intelligence/transcribe/${id}`, fd, { headers: { "Content-Type": "multipart/form-data" } }).then(r => r.data);
};
export const fullPipeline      = (id, file)  => {
  const fd = new FormData(); fd.append("file", file);
  return api.post(`/meetings/intelligence/pipeline/${id}`, fd, { headers: { "Content-Type": "multipart/form-data" }, timeout: 120000 }).then(r => r.data);
};

// ── AI Chat ────────────────────────────────────────────────────────────────
export const chat = (messages) =>
  api.post("/chat/", { messages }).then(r => r.data);

export default api;

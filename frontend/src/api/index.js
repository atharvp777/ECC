import api from "./client";
import { API_BASE_URL } from "../config";

// Dashboard
export const getDashboardStats = () => api.get("/dashboard/stats").then(r => r.data);

// Planning (deterministic, read-only)
export const getPlanningToday = () => api.get("/planning/today").then(r => r.data);
export const getPlanningDay = () => api.get("/planning/day").then(r => r.data);

// Projects
export const getProjects = () => api.get("/projects/").then(r => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then(r => r.data);
export const createProject = (data) => api.post("/projects/", data).then(r => r.data);
export const updateProject = (id, data) => api.patch(`/projects/${id}`, data).then(r => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`);

// Tasks
export const getTasks = (params = {}) => api.get("/tasks/", { params }).then(r => r.data);
export const getTodayTasks = () => api.get("/tasks/today").then(r => r.data);
export const getUpcomingTasks = (days = 7) => api.get("/tasks/upcoming", { params: { days } }).then(r => r.data);
export const createTask = (data) => api.post("/tasks/", data).then(r => r.data);
export const updateTask = (id, data) => api.patch(`/tasks/${id}`, data).then(r => r.data);
export const deleteTask = (id) => api.delete(`/tasks/${id}`);

// Tasks ↔ Google Calendar
export const linkTaskToCalendar = (id, data) =>
  api.post(`/tasks/${id}/calendar`, data).then(r => r.data);
export const unlinkTaskFromCalendar = (id) =>
  api.delete(`/tasks/${id}/calendar`).then(r => r.data);

// Notes
export const getNotes = (params = {}) => api.get("/notes/", { params }).then(r => r.data);
export const createNote = (data) => api.post("/notes/", data).then(r => r.data);
export const updateNote = (id, data) => api.patch(`/notes/${id}`, data).then(r => r.data);
export const deleteNote = (id) => api.delete(`/notes/${id}`);

// Project context (durable, project-scoped memory)
export const getProjectContext = (projectId) =>
  api.get(`/projects/${projectId}/context`).then(r => r.data);
export const createProjectContext = (projectId, data) =>
  api.post(`/projects/${projectId}/context`, data).then(r => r.data);
export const updateProjectContext = (projectId, id, data) =>
  api.patch(`/projects/${projectId}/context/${id}`, data).then(r => r.data);
export const deleteProjectContext = (projectId, id) =>
  api.delete(`/projects/${projectId}/context/${id}`);

// Documents
export const getDocuments = (params = {}) => api.get("/documents/", { params }).then(r => r.data);
export const uploadDocument = (formData) =>
  api.post("/documents/upload", formData, { headers: { "Content-Type": "multipart/form-data" } }).then(r => r.data);
export const updateDocument = (id, data) => api.patch(`/documents/${id}`, data).then(r => r.data);
export const deleteDocument = (id) => api.delete(`/documents/${id}`);
export const getDocumentDownloadUrl = (id) => `${API_BASE_URL}/documents/${id}/download`;

// Knowledge / Documents AI
export const searchDocs = (query, top_k = 5) =>
  api.post("/knowledge/search", { query, top_k }).then(r => r.data);

export const askDocs = (question) =>
  api.post("/knowledge/ask", { question }).then(r => r.data);

export const ingestDoc = (docId) =>
  api.post(`/knowledge/ingest/${docId}`).then(r => r.data);

export const indexStatus = () =>
  api.get("/knowledge/status").then(r => r.data);


// Integrations
export const getIntegrationStatus = () =>
  api.get("/integrations/status").then(r => r.data);

export const getGoogleEvents = (days = 14, maxResults = 20) =>
  api
    .get("/integrations/google/events", {
      params: { days, max_results: maxResults },
    })
    .then(r => r.data);

export const disconnectGoogle = () =>
  api.delete("/integrations/google/disconnect").then(r => r.data);
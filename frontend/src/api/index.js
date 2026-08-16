import api from "./client";

// Dashboard
export const getDashboardStats = () => api.get("/dashboard/stats").then(r => r.data);

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

// Notes
export const getNotes = (params = {}) => api.get("/notes/", { params }).then(r => r.data);
export const createNote = (data) => api.post("/notes/", data).then(r => r.data);
export const updateNote = (id, data) => api.patch(`/notes/${id}`, data).then(r => r.data);
export const deleteNote = (id) => api.delete(`/notes/${id}`);

// Documents
export const getDocuments = (params = {}) => api.get("/documents/", { params }).then(r => r.data);
export const uploadDocument = (formData) =>
  api.post("/documents/upload", formData, { headers: { "Content-Type": "multipart/form-data" } }).then(r => r.data);
export const updateDocument = (id, data) => api.patch(`/documents/${id}`, data).then(r => r.data);
export const deleteDocument = (id) => api.delete(`/documents/${id}`);

// Meetings
export const getMeetings = (params = {}) => api.get("/meetings/", { params }).then(r => r.data);
export const getMeeting = (id) => api.get(`/meetings/${id}`).then(r => r.data);
export const createMeeting = (data) => api.post("/meetings/", data).then(r => r.data);
export const updateMeeting = (id, data) => api.patch(`/meetings/${id}`, data).then(r => r.data);
export const deleteMeeting = (id) => api.delete(`/meetings/${id}`);
export const addActionItem = (meetingId, data) =>
  api.post(`/meetings/${meetingId}/action-items`, data).then(r => r.data);
export const updateActionItem = (meetingId, itemId, data) =>
  api.patch(`/meetings/${meetingId}/action-items/${itemId}`, data).then(r => r.data);


// Knowledge / Documents AI
export const searchDocs = (query, top_k = 5) =>
  api.post("/knowledge/search", { query, top_k }).then(r => r.data);

export const askDocs = (question) =>
  api.post("/knowledge/ask", { question }).then(r => r.data);

export const ingestDoc = (docId) =>
  api.post(`/knowledge/ingest/${docId}`).then(r => r.data);

export const indexStatus = () =>
  api.get("/knowledge/status").then(r => r.data);


// Meeting Intelligence
export const summarizeMeeting = (meetingId) =>
  api.post(`/meetings/intelligence/summarize/${meetingId}`).then(r => r.data);

export const transcribeMeeting = (meetingId, file) => {
  const formData = new FormData();
  formData.append("file", file);

  return api
    .post(`/meetings/intelligence/transcribe/${meetingId}`, formData)
    .then(r => r.data);
};

export const fullPipeline = (meetingId, file) => {
  const formData = new FormData();
  formData.append("file", file);

  return api
    .post(`/meetings/intelligence/pipeline/${meetingId}`, formData)
    .then(r => r.data);
};


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

export const getGithubRepos = (limit = 30) =>
  api
    .get("/integrations/github/repos", {
      params: { limit },
    })
    .then(r => r.data);

export const getGithubIssues = (repo, limit = 20) =>
  api
    .get("/integrations/github/issues", {
      params: { repo, limit },
    })
    .then(r => r.data);

export const getGithubPRs = (repo, limit = 20) =>
  api
    .get("/integrations/github/prs", {
      params: { repo, limit },
    })
    .then(r => r.data);

export const getGithubCommits = (repo, limit = 15) =>
  api
    .get("/integrations/github/commits", {
      params: { repo, limit },
    })
    .then(r => r.data);

export const pushTaskToGithub = (data) =>
  api.post("/integrations/github/push-task", data).then(r => r.data);
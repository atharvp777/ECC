import axios from "axios";
import { API_BASE_URL } from "../config";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

// Backend
export const getBackendHealth = () =>
  api.get("/").then((response) => response.data);

// Dashboard
export const getDashboardStats = () =>
  api.get("/dashboard/stats").then((response) => response.data);

// Tasks
export const getTodayTasks = () =>
  api.get("/tasks/today").then((response) => response.data);

export const getUpcomingTasks = (days = 7) =>
  api.get(`/tasks/upcoming?days=${days}`).then((response) => response.data);

export const updateTask = (id, data) =>
  api.patch(`/tasks/${id}`, data).then((response) => response.data);

// Projects
export const getProjects = () =>
  api.get("/projects/").then((response) => response.data);

export const createProject = (data) =>
  api.post("/projects/", data).then((response) => response.data);

export const deleteProject = (id) =>
  api.delete(`/projects/${id}`).then((response) => response.data);

export default api;

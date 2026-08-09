import axios from "axios";
import { API_BASE_URL } from "../config";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

export const getBackendHealth = () => api.get("/").then((response) => response.data);
export const getDashboardStats = () => api.get("/dashboard/stats").then(r => r.data);

export default api;

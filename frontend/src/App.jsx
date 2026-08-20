import { BrowserRouter, Routes, Route } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import Overview from "./pages/Overview";
import Projects from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Tasks from "./pages/Tasks";
import Notes from "./pages/Notes";
import Documents from "./pages/Documents";
import Calendar from "./pages/Calendar";
import Chat from "./pages/Chat";
import Integrations from "./pages/Integrations";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/projects/:id/tasks" element={<ProjectDetail />} />
          <Route path="/projects/:id/documents" element={<ProjectDetail />} />
          <Route path="/projects/:id/notes" element={<ProjectDetail />} />
          <Route path="/projects/:id/context" element={<ProjectDetail />} />
          <Route path="/projects/:id/ai" element={<ProjectDetail />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}

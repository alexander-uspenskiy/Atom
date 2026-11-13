import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui/Spinner";
import OverviewPage from "./pages/OverviewPage";
import ChatPage from "./pages/ChatPage";
import TelegramPage from "./pages/TelegramPage";
import ImagesPage from "./pages/ImagesPage";
import RunPage from "./pages/RunPage";
import RunsPage from "./pages/RunsPage";
import AgentsPage from "./pages/AgentsPage";
import SchedulesPage from "./pages/SchedulesPage";
import MemoryPage from "./pages/MemoryPage";
import ToolsPage from "./pages/ToolsPage";
import SkillsPage from "./pages/SkillsPage";
import ApprovalsPage from "./pages/ApprovalsPage";
import SettingsPage from "./pages/SettingsPage";

// Recharts is heavy: load the stats page on demand.
const StatsPage = lazy(() => import("./pages/StatsPage"));

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="telegram" element={<TelegramPage />} />
        <Route path="images" element={<ImagesPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="schedules" element={<SchedulesPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:id" element={<RunPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="skills" element={<SkillsPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="stats" element={<Suspense fallback={<Loading />}><StatsPage /></Suspense>} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

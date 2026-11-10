import { NavLink, Outlet } from "react-router-dom";
import {
  Activity, BarChart3, BookOpen, Bot, Brain, CalendarClock, History, Image as ImageIcon, LayoutDashboard, MessageSquare,
  Monitor, Moon, ShieldCheck, Sun, Settings as SettingsIcon, Wrench, type LucideIcon,
} from "lucide-react";
import { useGlobalEvents, useStatus } from "../api/hooks";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/cn";
import { ModelSwitcher } from "./ModelSwitcher";

interface NavDef { to: string; label: string; icon: LucideIcon; end?: boolean; badge?: "approvals" | "runs" }
const NAV: NavDef[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/images", label: "Images", icon: ImageIcon },
  { to: "/approvals", label: "Approvals", icon: ShieldCheck, badge: "approvals" },
  { to: "/runs", label: "Runs", icon: History, badge: "runs" },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/schedules", label: "Schedules", icon: CalendarClock },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/skills", label: "Skills", icon: BookOpen },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/stats", label: "Stats", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function LlmIndicator() {
  const { data, isError } = useStatus();
  const llm = data?.llm;
  const slots = llm?.slots ?? [];
  const busy = slots.filter((s) => s.busy).length;
  const healthy = !isError && llm?.healthy === true;
  const known = !isError && llm?.healthy !== undefined;
  return (
    <div className="flex items-center gap-2 px-2 py-1.5" title={`LLM ${healthy ? "healthy" : known ? "unreachable" : "unknown"}${llm?.base_url ? ` · ${llm.base_url}` : ""}`}>
      <span
        className={cn("h-2.5 w-2.5 shrink-0 rounded-full", healthy ? "bg-ok" : known || isError ? "bg-err" : "bg-muted", healthy && busy > 0 && "animate-pulseDot")}
        aria-hidden
      />
      <div className="hidden min-w-0 flex-1 lg:block">
        <ModelSwitcher>
          <div className="truncate text-xs font-medium">{llm?.model ?? (isError ? "Backend offline" : "—")}</div>
          <div className="text-[11px] text-muted">
            {isError ? "no connection" : healthy ? `${busy}/${slots.length || "?"} slots busy` : "LLM down · click to switch"}
          </div>
        </ModelSwitcher>
      </div>
      <span className="sr-only lg:hidden">{healthy ? "LLM healthy" : "LLM down"}</span>
    </div>
  );
}

export function Layout() {
  useGlobalEvents();
  const { data: status } = useStatus();
  const { mode, toggle } = useTheme();
  const pending = status?.pending_actions ?? 0;
  const running = status?.runs?.running?.length ?? 0;
  const badgeFor = (b?: NavDef["badge"]) => (b === "approvals" ? pending : b === "runs" ? running : 0);

  return (
    <div className="flex h-full">
      <aside className="flex w-14 shrink-0 flex-col border-r border-line bg-surface lg:w-52" aria-label="Primary">
        <div className="flex h-12 items-center gap-2 border-b border-line px-3.5">
          <Activity className="h-5 w-5 shrink-0 text-accent" aria-hidden />
          <span className="hidden text-sm font-semibold tracking-tight lg:inline">Atom</span>
          <span className="ml-auto hidden text-[10px] text-muted lg:inline">{status?.version ? `v${status.version}` : ""}</span>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-1.5">
          {NAV.map((n) => {
            const count = badgeFor(n.badge);
            return (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                title={n.label}
                className={({ isActive }) =>
                  cn(
                    "relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium transition-colors",
                    isActive ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface2 hover:text-fg",
                  )
                }
              >
                <n.icon className="h-4 w-4 shrink-0" aria-hidden />
                <span className="hidden lg:inline">{n.label}</span>
                {count > 0 && (
                  <span
                    className={cn(
                      "ml-auto hidden min-w-[1.25rem] rounded-full px-1.5 text-center text-[11px] font-semibold leading-5 lg:inline-block",
                      n.badge === "approvals" ? "bg-warn text-white dark:text-black" : "bg-info/15 text-info",
                    )}
                    aria-label={`${count} ${n.badge === "approvals" ? "pending approvals" : "running runs"}`}
                  >
                    {count}
                  </span>
                )}
                {count > 0 && (
                  <span className={cn("absolute right-1.5 top-1 h-2 w-2 rounded-full lg:hidden", n.badge === "approvals" ? "bg-warn" : "bg-info")} aria-hidden />
                )}
              </NavLink>
            );
          })}
        </nav>
        <div className="border-t border-line p-1.5">
          <LlmIndicator />
          <button
            type="button"
            onClick={toggle}
            aria-label={`Theme: ${mode}. Click to change`}
            title={`Theme: ${mode}`}
            className="mt-0.5 flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-sm text-muted hover:bg-surface2 hover:text-fg"
          >
            {mode === "auto" ? <Monitor className="h-4 w-4 shrink-0" /> : mode === "dark" ? <Moon className="h-4 w-4 shrink-0" /> : <Sun className="h-4 w-4 shrink-0" />}
            <span className="hidden lg:inline">{mode === "auto" ? "Auto theme" : mode === "dark" ? "Dark theme" : "Light theme"}</span>
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
        <footer className="flex h-7 shrink-0 items-center justify-center gap-1.5 border-t border-line bg-surface px-3 text-[11px] text-muted">
          <span>Atom · by Alexander Uspenskiy ·</span>
          <a href="https://github.com/alexander-uspenskiy/Atom" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-fg">
            <svg viewBox="0 0 16 16" className="h-3 w-3 fill-current" aria-hidden><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38v-1.33c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.8.06 1.23.83 1.23.83.72 1.22 1.88.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg> GitHub
          </a>
        </footer>
      </div>
    </div>
  );
}

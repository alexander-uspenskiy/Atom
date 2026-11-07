import type {
  Agent, AgentInput, ChatBody, ChatEvent, Conversation, ConversationInfo, Memory, MemoryInput, PendingAction,
  RunDetail, RunList, RunOverrides, RunSummary, Schedule, SchedulePreview, ScheduleInput, ScheduleTrigger,
  SettingsResponse, SettingValue, Skill, StatsSummary, Status, ToolInfo,
} from "./types";
import { parseJSON, readSSE } from "./sse";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailText(d: unknown): string {
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((e) => (e && typeof e === "object" && "msg" in e ? `${(e as { loc?: unknown[] }).loc?.slice(1).join(".") ?? ""} ${(e as { msg: string }).msg}`.trim() : String(e)))
      .join("; ");
  }
  return d ? JSON.stringify(d) : "";
}

async function errorFrom(res: Response): Promise<ApiError> {
  let msg = `${res.status} ${res.statusText}`.trim();
  try {
    const text = await res.text();
    const j = parseJSON<{ detail?: unknown }>(text);
    const d = j ? detailText(j.detail) : text.slice(0, 200);
    if (d) msg = d;
  } catch {
    /* ignore */
  }
  return new ApiError(res.status, msg);
}

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await errorFrom(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export interface RunFilters { status?: string; agent_id?: string; schedule_id?: string; q?: string; limit?: number; offset?: number }
export interface MemoryFilters { q?: string; scope?: string; pinned?: boolean; status?: string; limit?: number }

export const api = {
  status: () => req<Status>("GET", "/status"),

  settings: () => req<SettingsResponse>("GET", "/settings"),
  saveSettings: (values: Record<string, SettingValue>) => req<SettingsResponse>("PUT", "/settings", { values }),

  agents: () => req<Agent[]>("GET", "/agents"),
  createAgent: (a: AgentInput) => req<Agent>("POST", "/agents", a),
  updateAgent: (id: string, a: AgentInput) => req<Agent>("PUT", `/agents/${encodeURIComponent(id)}`, a),
  deleteAgent: (id: string) => req<void>("DELETE", `/agents/${encodeURIComponent(id)}`),
  tools: () => req<ToolInfo[]>("GET", "/tools"),
  runAgent: (id: string, body: { task: string; start_url?: string | null; overrides?: RunOverrides }) =>
    req<{ run_id: string }>("POST", `/agents/${encodeURIComponent(id)}/run`, body),

  runs: (f: RunFilters = {}) => req<RunList>("GET", `/runs${qs({ limit: 50, ...f })}`),
  run: (id: string) => req<RunDetail>("GET", `/runs/${encodeURIComponent(id)}`),
  stopRun: (id: string) => req<RunSummary>("POST", `/runs/${encodeURIComponent(id)}/stop`),
  shotUrl: (id: string, n: number) => `/api/runs/${encodeURIComponent(id)}/shots/${n}.jpg`,
  traceUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/trace.zip`,
  runEventsUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/events`,
  globalEventsUrl: "/api/events",

  schedules: () => req<Schedule[]>("GET", "/schedules"),
  createSchedule: (s: ScheduleInput) => req<Schedule>("POST", "/schedules", s),
  updateSchedule: (id: string, s: ScheduleInput) => req<Schedule>("PUT", `/schedules/${encodeURIComponent(id)}`, s),
  deleteSchedule: (id: string) => req<void>("DELETE", `/schedules/${encodeURIComponent(id)}`),
  runSchedule: (id: string) => req<{ run_id: string }>("POST", `/schedules/${encodeURIComponent(id)}/run`),
  toggleSchedule: (id: string, enabled: boolean) =>
    req<Schedule>("POST", `/schedules/${encodeURIComponent(id)}/toggle`, { enabled }),
  previewSchedule: (trigger: ScheduleTrigger, timezone: string, count = 5, signal?: AbortSignal) =>
    req<SchedulePreview>("POST", "/schedules/preview", { trigger, timezone, count }, signal),

  memories: (f: MemoryFilters = {}) => req<Memory[]>("GET", `/memories${qs({ limit: 200, ...f })}`),
  createMemory: (m: MemoryInput) => req<Memory>("POST", "/memories", m),
  updateMemory: (id: string, m: Partial<MemoryInput>) => req<Memory>("PUT", `/memories/${encodeURIComponent(id)}`, m),
  deleteMemory: (id: string) => req<void>("DELETE", `/memories/${encodeURIComponent(id)}`),

  skills: () => req<Skill[]>("GET", "/skills"),
  createSkill: (s: Skill) => req<Skill>("POST", "/skills", s),
  updateSkill: (name: string, s: Skill) => req<Skill>("PUT", `/skills/${encodeURIComponent(name)}`, s),
  deleteSkill: (name: string) => req<void>("DELETE", `/skills/${encodeURIComponent(name)}`),

  actions: (status?: string) => req<PendingAction[]>("GET", `/actions${qs({ status })}`),
  approveAction: (id: string, payload?: unknown) =>
    req<PendingAction>("POST", `/actions/${encodeURIComponent(id)}/approve`, payload === undefined ? {} : { payload }),
  rejectAction: (id: string) => req<PendingAction>("POST", `/actions/${encodeURIComponent(id)}/reject`, {}),

  conversations: () => req<ConversationInfo[]>("GET", "/conversations"),
  createConversation: (title: string | null = null) => req<ConversationInfo>("POST", "/conversations", { title }),
  conversation: (id: string) => req<Conversation>("GET", `/conversations/${encodeURIComponent(id)}`),
  renameConversation: (id: string, title: string) =>
    req<ConversationInfo>("PUT", `/conversations/${encodeURIComponent(id)}`, { title }),
  deleteConversation: (id: string) => req<void>("DELETE", `/conversations/${encodeURIComponent(id)}`),

  stats: (days: number) => req<StatsSummary>("GET", `/stats/summary${qs({ days })}`),
};

/** POST a chat message and stream the SSE response. Resolves when the stream ends; abort via `signal`. */
export async function streamChat(
  conversationId: string,
  body: ChatBody,
  onEvent: (ev: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorFrom(res);
  await readSSE(
    res,
    (raw) => {
      const ev = parseJSON<ChatEvent>(raw);
      if (ev && typeof ev.type === "string") onEvent(ev);
    },
    signal,
  );
}

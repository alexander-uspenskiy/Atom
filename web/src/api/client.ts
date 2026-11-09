import type {
  Agent, AgentInput, ChatBody, ChatEvent, ContextUsage, Conversation, ConversationInfo, Project, Memory, MemoryInput, PendingAction,
  RunDetail, RunList, RunOverrides, RunSummary, Schedule, SchedulePreview, ScheduleInput, ScheduleTrigger,
  UploadInfo, ConnectorsPayload, McpServerConfig, McpStatus, Variable, VariableIn, SettingsResponse, SettingValue, Skill, StatsSummary, Status, ToolInfo,
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
  chatTools: () => req<ToolInfo[]>("GET", "/chat/tools"),
  fsDirs: (path: string) => req<{ path: string; parent: string | null; home: string; dirs: string[] }>("GET", `/fs/dirs?path=${encodeURIComponent(path)}`),
  mcp: () => req<McpStatus>("GET", "/mcp"),
  mcpReload: () => req<McpStatus>("POST", "/mcp/reload"),
  mcpSave: (name: string, cfg: McpServerConfig) => req<McpStatus>("PUT", `/mcp/servers/${encodeURIComponent(name)}`, cfg),
  connectors: () => req<ConnectorsPayload>("GET", "/connectors"),
  connectorSave: (name: string, body: { type: string; enabled: boolean; config: Record<string, unknown> }) => req<ConnectorsPayload>("PUT", `/connectors/${encodeURIComponent(name)}`, body),
  connectorDelete: (name: string) => req<ConnectorsPayload>("DELETE", `/connectors/${encodeURIComponent(name)}`),
  connectorTest: (name: string) => req<{ ok: boolean; message: string }>("POST", `/connectors/${encodeURIComponent(name)}/test`),
  connectorOAuthStart: (name: string) => req<{ auth_url: string; redirect_uri: string }>("POST", `/connectors/${encodeURIComponent(name)}/oauth/start`),
  connectorSignOut: (name: string) => req<ConnectorsPayload>("POST", `/connectors/${encodeURIComponent(name)}/oauth/signout`),
  variables: () => req<Variable[]>("GET", "/variables"),
  variableSave: (name: string, v: VariableIn) => req<Variable>("PUT", `/variables/${encodeURIComponent(name)}`, v),
  variableDelete: (name: string) => req<void>("DELETE", `/variables/${encodeURIComponent(name)}`),
  mcpDelete: (name: string) => req<McpStatus>("DELETE", `/mcp/servers/${encodeURIComponent(name)}`),
  uploadImage: (dataUrl: string, name = "") => req<UploadInfo>("POST", "/uploads", { data_url: dataUrl, name }),
  /** Raw-body upload (documents: PDF, Markdown, text) — avoids base64 inflation. */
  uploadFile: async (file: File) => {
    const res = await fetch(`/api/uploads${qs({ name: file.name })}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
    if (!res.ok) throw await errorFrom(res);
    return (await res.json()) as UploadInfo;
  },
  uploadInfo: (id: string) => req<UploadInfo>("GET", `/uploads/${encodeURIComponent(id)}/info`),
  uploadUrl: (id: string) => `/api/uploads/${encodeURIComponent(id)}`,
  runAgent: (id: string, body: { task: string; start_url?: string | null; overrides?: RunOverrides; images?: string[] }) =>
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

  skills: (projectId?: string | null) => req<Skill[]>("GET", `/skills${qs({ project_id: projectId ?? undefined })}`),
  createSkill: (s: Skill, projectId?: string | null) => req<Skill>("POST", `/skills${qs({ project_id: projectId ?? undefined })}`, s),
  updateSkill: (name: string, s: Skill, projectId?: string | null) =>
    req<Skill>("PUT", `/skills/${encodeURIComponent(name)}${qs({ project_id: projectId ?? undefined })}`, s),
  deleteSkill: (name: string, projectId?: string | null) =>
    req<void>("DELETE", `/skills/${encodeURIComponent(name)}${qs({ project_id: projectId ?? undefined })}`),

  actions: (status?: string) => req<PendingAction[]>("GET", `/actions${qs({ status })}`),
  approveAction: (id: string, payload?: unknown) =>
    req<PendingAction>("POST", `/actions/${encodeURIComponent(id)}/approve`, payload === undefined ? {} : { payload }),
  rejectAction: (id: string) => req<PendingAction>("POST", `/actions/${encodeURIComponent(id)}/reject`, {}),

  conversations: () => req<ConversationInfo[]>("GET", "/conversations"),
  createConversation: (title: string | null = null, project_id: string | null = null) =>
    req<ConversationInfo>("POST", "/conversations", { title, project_id }),
  projects: () => req<Project[]>("GET", "/projects"),
  createProject: (b: { name: string; folder: string }) => req<Project>("POST", "/projects", b),
  updateProject: (id: string, b: { name: string; folder: string }) => req<Project>("PUT", `/projects/${encodeURIComponent(id)}`, b),
  deleteProject: (id: string) => req<void>("DELETE", `/projects/${encodeURIComponent(id)}`),
  conversation: (id: string) => req<Conversation>("GET", `/conversations/${encodeURIComponent(id)}`),
  conversationContext: (id: string, o: { effort?: string; thinking?: boolean } = {}) =>
    req<ContextUsage>("GET", `/conversations/${encodeURIComponent(id)}/context${qs({ effort: o.effort, thinking: o.thinking })}`),
  renameConversation: (id: string, title: string) =>
    req<ConversationInfo>("PUT", `/conversations/${encodeURIComponent(id)}`, { title }),
  deleteConversation: (id: string) => req<void>("DELETE", `/conversations/${encodeURIComponent(id)}`),

  decideApproval: (callId: string, approve: boolean) =>
    req<{ ok: boolean }>("POST", `/chat/approvals/${encodeURIComponent(callId)}`, { approve }),

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

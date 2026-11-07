// Types mirror docs/DASHBOARD_API.md (v1). Everything the backend may omit is optional/nullable.

export type RunStatus = "queued" | "running" | "done" | "failed" | "budget" | "stopped";
export type Thinking = "inherit" | "off" | "auto" | "on";
export type Effort = "inherit" | "low" | "medium" | "xhigh";

export interface LlmSlot { id: number; busy: boolean; n_ctx?: number; role?: string }
export interface Status {
  version?: string;
  llm?: { healthy?: boolean; base_url?: string; model?: string; slots?: LlmSlot[] };
  runs?: { running?: string[]; queued?: number; max_concurrent?: number };
  scheduler?: { running?: boolean; jobs?: number };
  pending_actions?: number;
}

export type SettingType = "text" | "number" | "boolean" | "select" | "slider";
export interface SettingField {
  key: string; label: string; group?: string; type: SettingType;
  options?: string[]; min?: number; max?: number; step?: number; help?: string;
}
export type SettingValue = string | number | boolean | null;
export interface SettingsResponse {
  values: Record<string, SettingValue>;
  defaults: Record<string, SettingValue>;
  schema: SettingField[];
}

export interface Agent {
  id: string; name: string; description?: string | null; instructions?: string | null;
  start_url?: string | null; allowed_domains?: string[] | null; allow_private?: boolean;
  tools?: string[] | null; skills?: string[] | null; memory_scope?: "none" | "global" | "agent";
  thinking?: Thinking; effort?: Effort; max_steps?: number | null; temperature?: number | null;
  profile?: string | null; is_default?: boolean; created_at?: number; updated_at?: number;
}
export type AgentInput = Omit<Agent, "id" | "created_at" | "updated_at" | "is_default">;
export interface ToolInfo { name: string; description?: string; side_effect?: boolean }
export interface RunOverrides { thinking?: Thinking; effort?: Effort; max_steps?: number | null; temperature?: number | null }

export interface RunSummary {
  id: string; task?: string; agent_id?: string | null; agent_name?: string | null;
  schedule_id?: string | null; trigger?: "manual" | "schedule" | "chat" | "api" | string;
  status: RunStatus; success?: boolean | null; result?: string | null; error?: string | null;
  queued_at?: number | null; started_at?: number | null; finished_at?: number | null; steps?: number;
  prompt_tokens?: number; cached_tokens?: number; processed_tokens?: number; completion_tokens?: number;
  llm_seconds?: number; tool_seconds?: number; wall_seconds?: number;
  thinking?: string | null; effort?: string | null; current_url?: string | null; last_screenshot?: number | null;
}
export interface Step {
  idx: number; kind: "llm" | "tool" | "compact" | "note" | string; name?: string | null;
  args?: unknown; result?: string | null; ok?: boolean | null; url?: string | null; think?: boolean;
  prompt_tokens?: number; cached_tokens?: number; processed_tokens?: number; completion_tokens?: number;
  llm_seconds?: number; prefill_ms?: number; decode_ms?: number; decode_tps?: number;
  tool_seconds?: number; ts?: number; screenshot?: number | null;
}
export interface RunDetail { run: RunSummary; steps: Step[]; events_url?: string }
export interface RunList { items: RunSummary[]; total: number }

export interface ToolCallInfo { id?: string; name: string; arguments?: unknown }
export interface RunTotals {
  steps?: number; prompt_tokens?: number; cached_tokens?: number; processed_tokens?: number;
  completion_tokens?: number; llm_seconds?: number; tool_seconds?: number; wall_seconds?: number;
}
interface RunEventBase { seq: number; ts?: number; run_id?: string }
export type RunEvent =
  | (RunEventBase & { type: "run_status"; status: RunStatus })
  | (RunEventBase & { type: "step_start"; step: number; think?: boolean; effort?: string })
  | (RunEventBase & { type: "token"; step: number; channel: "content" | "reasoning"; text: string })
  | (RunEventBase & {
      type: "llm_end"; step: number; prompt_tokens?: number; cached_tokens?: number; processed_tokens?: number;
      completion_tokens?: number; llm_seconds?: number; prefill_ms?: number; decode_ms?: number;
      prefill_tps?: number; decode_tps?: number; finish_reason?: string; content?: string | null;
      tool_calls?: ToolCallInfo[];
    })
  | (RunEventBase & { type: "tool_start"; step: number; call_id?: string; name: string; arguments?: unknown })
  | (RunEventBase & {
      type: "tool_end"; step: number; call_id?: string; name: string; ok?: boolean; result?: string;
      tool_seconds?: number; url?: string | null;
    })
  | (RunEventBase & { type: "screenshot"; step: number; n: number; url?: string; title?: string })
  | (RunEventBase & { type: "compact"; step: number; summarized_actions?: number })
  | (RunEventBase & {
      type: "run_finished"; status: RunStatus; success?: boolean; result?: string | null;
      error?: string | null; totals?: RunTotals;
    });

export type ScheduleTrigger =
  | { type: "cron"; expr: string }
  | { type: "interval"; seconds: number }
  | { type: "once"; at: string };
export interface Schedule {
  id: string; name: string; agent_id?: string | null; agent_name?: string | null; task: string;
  start_url?: string | null; trigger: ScheduleTrigger; timezone?: string; enabled: boolean;
  next_run_at?: number | null; last_run_at?: number | null; last_run_id?: string | null;
  last_status?: RunStatus | null; run_count?: number; created_by?: "user" | "assistant" | string;
  created_at?: number; updated_at?: number;
}
export interface ScheduleInput {
  name: string; agent_id: string | null; task: string; start_url?: string | null;
  trigger: ScheduleTrigger; timezone: string; enabled: boolean;
}
export interface SchedulePreview { next: string[]; description: string; error?: string | null }

export interface Memory {
  id: string; title: string; content: string; tags?: string[]; scope: string; pinned?: boolean;
  status?: "active" | "pending"; source?: string; created_at?: number; updated_at?: number;
  last_used_at?: number | null; use_count?: number;
}
export type MemoryInput = Pick<Memory, "title" | "content" | "tags" | "scope" | "pinned">;

export interface Skill {
  name: string; description?: string; when_to_use?: string; body?: string; enabled?: boolean;
  created_by?: string; updated_at?: number;
}

export type ActionKind =
  | "create_schedule" | "create_agent" | "create_skill" | "save_memory" | "update_schedule" | "delete_schedule";
export interface PendingAction {
  id: string; kind: ActionKind | string; summary?: string; payload?: unknown;
  status: "pending" | "approved" | "rejected" | "failed"; created_by?: string;
  conversation_id?: string | null; created_at?: number; decided_at?: number | null; result?: unknown;
}

export interface MessageStats {
  prompt_tokens?: number; cached_tokens?: number; processed_tokens?: number; completion_tokens?: number;
  llm_seconds?: number; decode_tps?: number; prefill_tps?: number; think?: boolean;
}
export interface Message {
  id: string; role: "user" | "assistant" | "tool"; content?: string | null; reasoning?: string | null;
  tool_calls?: ToolCallInfo[] | null; tool_call_id?: string | null; action_id?: string | null;
  run_id?: string | null; stats?: MessageStats | null; created_at?: number;
}
export interface ConversationInfo { id: string; title?: string | null; updated_at?: number; message_count?: number }
export interface Conversation { id: string; title?: string | null; messages: Message[] }
export interface ChatBody { content: string; thinking: boolean; effort: "low" | "medium" | "xhigh" }

export type ChatEvent =
  | { type: "message_start"; message_id?: string }
  | { type: "token"; channel: "content" | "reasoning"; text: string }
  | { type: "tool_call"; id?: string; name: string; arguments?: unknown }
  | { type: "tool_result"; id?: string; name?: string; ok?: boolean; result?: unknown }
  | { type: "action_proposed"; action: PendingAction }
  | { type: "run_started"; run_id: string }
  | ({ type: "llm_end" } & MessageStats)
  | { type: "message_end"; message: Message }
  | { type: "done" }
  | { type: "error"; detail?: string };

export interface StatsSummary {
  days: number;
  runs?: { total?: number; done?: number; failed?: number; budget?: number; stopped?: number; success_rate?: number };
  tokens?: { input?: number; cached?: number; processed?: number; output?: number; cache_hit_rate?: number };
  timing?: { avg_wall_s?: number; avg_llm_s_per_step?: number; avg_decode_tps?: number; avg_prefill_tps?: number };
  by_day?: { day: string; runs?: number; input?: number; cached?: number; output?: number; llm_seconds?: number }[];
  by_agent?: { agent_id?: string; agent_name?: string; runs?: number; success_rate?: number; input?: number; output?: number; avg_wall_s?: number }[];
  slowest_runs?: RunSummary[];
}

export type GlobalEvent =
  | { type: "run_queued" | "run_started" | "run_finished"; run: RunSummary }
  | { type: "schedule_fired"; schedule_id: string; run_id: string }
  | { type: "action_pending" | "action_decided"; action: PendingAction }
  | { type: "status"; status: Status };

export interface McpServerConfig {
  command?: string; args?: string[]; env?: Record<string, string>; cwd?: string;
  url?: string; headers?: Record<string, string>; disabled?: boolean;
}
export interface McpServer {
  name: string; config: McpServerConfig;
  state: "connected" | "error" | "disabled" | "pending" | string;
  tools: number; tool_names: string[]; error: string | null;
}
export interface McpStatus { config_path: string; servers: McpServer[] }

export interface Variable {
  name: string; secret: boolean; value: string | null; has_value: boolean;
  description: string; domains: string[]; updated_at: number;
}
export interface VariableIn { value?: string; secret: boolean; description: string; domains: string[] }

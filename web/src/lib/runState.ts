import type { RunEvent, RunStatus, RunSummary, RunTotals, Step, ToolCallInfo } from "../api/types";

/** A row in the step timeline (LLM call or tool call), built from stored steps or live events. */
export interface TItem {
  id: string;
  kind: "llm" | "tool" | "compact" | "note";
  step?: number;
  name: string;
  args?: unknown;
  result?: string | null;
  ok?: boolean | null;
  running?: boolean;
  think?: boolean;
  effort?: string;
  prompt_tokens?: number;
  cached_tokens?: number;
  processed_tokens?: number;
  completion_tokens?: number;
  llm_seconds?: number;
  prefill_ms?: number;
  decode_ms?: number;
  decode_tps?: number;
  prefill_tps?: number;
  tool_seconds?: number;
  content?: string;
  reasoning?: string;
  toolCalls?: ToolCallInfo[];
  callId?: string;
  url?: string | null;
  screenshot?: number | null;
  ts?: number;
  finish?: string;
}

export type Phase = "idle" | "waiting" | "thinking" | "answering";
export interface NowState { step: number; phase: Phase; think?: boolean; effort?: string; reasoning: string; content: string }
export interface ToolNow { name: string; args: unknown; callId?: string; startedAt: number }
export interface Shot { n: number; url?: string; title?: string }

export interface LiveState {
  status: RunStatus | null;
  items: TItem[];
  now: NowState | null;
  tool: ToolNow | null;
  shot: Shot | null;
  totals: { prompt: number; cached: number; completion: number; llm: number; tool: number; steps: number };
  finished: { status: RunStatus; success?: boolean; result?: string | null; error?: string | null; totals?: RunTotals } | null;
  firstTs: number | null;
  currentUrl: string | null;
}

export const initialLive: LiveState = {
  status: null, items: [], now: null, tool: null, shot: null,
  totals: { prompt: 0, cached: 0, completion: 0, llm: 0, tool: 0, steps: 0 },
  finished: null, firstTs: null, currentUrl: null,
};

export type LiveAction = RunEvent | { type: "__reset" };

const n = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);

function patchLast(items: TItem[], pred: (i: TItem) => boolean, patch: (i: TItem) => TItem): TItem[] {
  for (let i = items.length - 1; i >= 0; i--) {
    if (pred(items[i])) {
      const next = items.slice();
      next[i] = patch(items[i]);
      return next;
    }
  }
  return items;
}

/** Pure reducer. De-duplication by `seq` happens before dispatch (see useRunStream). */
export function liveReducer(s: LiveState, ev: LiveAction): LiveState {
  if (ev.type === "__reset") return initialLive;
  const firstTs = s.firstTs ?? (typeof ev.ts === "number" ? ev.ts : null);
  const base = firstTs === s.firstTs ? s : { ...s, firstTs };
  switch (ev.type) {
    case "run_status":
      return { ...base, status: ev.status };
    case "step_start": {
      const item: TItem = {
        id: `llm-${ev.step}`, kind: "llm", step: ev.step, name: "LLM call", running: true,
        think: ev.think, effort: ev.effort, reasoning: "", content: "", ts: ev.ts,
      };
      const items = base.items.some((i) => i.id === item.id) ? base.items : [...base.items, item];
      return { ...base, items, now: { step: ev.step, phase: "waiting", think: ev.think, effort: ev.effort, reasoning: "", content: "" } };
    }
    case "token": {
      const key = ev.channel === "reasoning" ? "reasoning" : "content";
      const id = `llm-${ev.step}`;
      let items = base.items;
      if (!items.some((i) => i.id === id)) {
        items = [...items, { id, kind: "llm", step: ev.step, name: "LLM call", running: true, reasoning: "", content: "", ts: ev.ts }];
      }
      items = patchLast(items, (i) => i.id === id, (i) => ({ ...i, [key]: (i[key] ?? "") + ev.text }));
      const cur = base.now && base.now.step === ev.step ? base.now : { step: ev.step, phase: "waiting" as Phase, reasoning: "", content: "" };
      const now: NowState = { ...cur, phase: key === "reasoning" ? "thinking" : "answering", [key]: cur[key] + ev.text };
      return { ...base, items, now };
    }
    case "llm_end": {
      const id = `llm-${ev.step}`;
      let items = base.items;
      if (!items.some((i) => i.id === id)) items = [...items, { id, kind: "llm", step: ev.step, name: "LLM call", reasoning: "", content: "", ts: ev.ts }];
      items = patchLast(items, (i) => i.id === id, (i) => ({
        ...i, running: false, prompt_tokens: ev.prompt_tokens, cached_tokens: ev.cached_tokens, processed_tokens: ev.processed_tokens,
        completion_tokens: ev.completion_tokens, llm_seconds: ev.llm_seconds, prefill_ms: ev.prefill_ms, decode_ms: ev.decode_ms,
        decode_tps: ev.decode_tps, prefill_tps: ev.prefill_tps, finish: ev.finish_reason,
        content: ev.content ?? i.content, toolCalls: ev.tool_calls ?? [],
      }));
      const cur = base.now;
      const now: NowState | null = cur && cur.step === ev.step
        ? { ...cur, phase: "idle", content: ev.content ?? cur.content }
        : { step: ev.step, phase: "idle", reasoning: "", content: ev.content ?? "" };
      const t = base.totals;
      return {
        ...base, items, now,
        totals: { ...t, prompt: t.prompt + n(ev.prompt_tokens), cached: t.cached + n(ev.cached_tokens), completion: t.completion + n(ev.completion_tokens), llm: t.llm + n(ev.llm_seconds), steps: t.steps + 1 },
      };
    }
    case "tool_start": {
      const item: TItem = {
        id: `tool-${ev.call_id ?? `${ev.step}-${base.items.length}`}`, kind: "tool", step: ev.step, name: ev.name,
        args: ev.arguments, running: true, callId: ev.call_id, ts: ev.ts,
      };
      if (base.items.some((i) => i.id === item.id)) return base;
      return { ...base, items: [...base.items, item], tool: { name: ev.name, args: ev.arguments, callId: ev.call_id, startedAt: ev.ts ? ev.ts * 1000 : Date.now() } };
    }
    case "tool_end": {
      const match = (i: TItem) =>
        i.kind === "tool" && i.running === true && (ev.call_id ? i.callId === ev.call_id : i.name === ev.name);
      let items = base.items;
      if (!items.some(match)) {
        items = [...items, { id: `tool-${ev.call_id ?? `${ev.step}-${items.length}`}`, kind: "tool", step: ev.step, name: ev.name, running: true, callId: ev.call_id }];
      }
      items = patchLast(items, match, (i) => ({ ...i, running: false, ok: ev.ok ?? null, result: ev.result ?? null, tool_seconds: ev.tool_seconds, url: ev.url ?? null }));
      const t = base.totals;
      return { ...base, items, tool: null, currentUrl: ev.url ?? base.currentUrl, totals: { ...t, tool: t.tool + n(ev.tool_seconds) } };
    }
    case "screenshot": {
      // Attach to the most recent tool row that has no screenshot yet.
      const items = patchLast(base.items, (i) => i.kind === "tool" && i.screenshot == null, (i) => ({ ...i, screenshot: ev.n }));
      return { ...base, items, shot: { n: ev.n, url: ev.url, title: ev.title }, currentUrl: ev.url ?? base.currentUrl };
    }
    case "compact":
      return {
        ...base,
        items: [...base.items, { id: `compact-${ev.seq ?? base.items.length}`, kind: "compact", step: ev.step, name: "Context compacted", result: `${ev.summarized_actions ?? "?"} actions summarized`, ts: ev.ts }],
      };
    case "run_finished": {
      const items = base.items.map((i) => (i.running ? { ...i, running: false } : i));
      return {
        ...base, items, status: ev.status, tool: null, now: base.now ? { ...base.now, phase: "idle" } : null,
        finished: { status: ev.status, success: ev.success, result: ev.result, error: ev.error, totals: ev.totals },
      };
    }
    default:
      return base;
  }
}

/** Timeline rows for a finished run (from GET /api/runs/{id}). */
export function stepsToItems(steps: Step[] | undefined | null): TItem[] {
  return (steps ?? []).map((s, k) => ({
    id: `s-${s.idx ?? k}-${k}`,
    kind: (s.kind === "llm" || s.kind === "tool" || s.kind === "compact" ? s.kind : "note") as TItem["kind"],
    name: s.name ?? (s.kind === "llm" ? "LLM call" : s.kind),
    args: s.args, result: s.result, ok: s.ok, think: s.think,
    prompt_tokens: s.prompt_tokens, cached_tokens: s.cached_tokens, processed_tokens: s.processed_tokens,
    completion_tokens: s.completion_tokens, llm_seconds: s.llm_seconds, prefill_ms: s.prefill_ms, decode_ms: s.decode_ms,
    decode_tps: s.decode_tps, tool_seconds: s.tool_seconds, url: s.url, screenshot: s.screenshot, ts: s.ts,
  }));
}

export const isActive = (s?: string | null): boolean => s === "queued" || s === "running";
export type { RunSummary };

import { useEffect, useReducer } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, type MemoryFilters, type RunFilters } from "./client";
import { useSSE } from "./sse";
import type { GlobalEvent, Status } from "./types";

export const qk = {
  status: ["status"] as const,
  settings: ["settings"] as const,
  agents: ["agents"] as const,
  tools: ["tools"] as const,
  mcp: ["mcp"] as const,
  variables: ["variables"] as const,
  connectors: ["connectors"] as const,
  runs: (f?: RunFilters) => ["runs", f ?? {}] as const,
  run: (id: string) => ["run", id] as const,
  schedules: ["schedules"] as const,
  memories: (f?: MemoryFilters) => ["memories", f ?? {}] as const,
  skills: ["skills"] as const,
  actions: (s?: string) => ["actions", s ?? "all"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  stats: (d: number) => ["stats", d] as const,
};

export const useStatus = () => useQuery({ queryKey: qk.status, queryFn: api.status, refetchInterval: 15000 });
export const useSettings = () => useQuery({ queryKey: qk.settings, queryFn: api.settings });
export const useAgents = () => useQuery({ queryKey: qk.agents, queryFn: api.agents });
export const useTools = () => useQuery({ queryKey: qk.tools, queryFn: api.tools, staleTime: 60000 });
export const useVariables = () => useQuery({ queryKey: qk.variables, queryFn: api.variables });
export const useConnectors = () => useQuery({ queryKey: qk.connectors, queryFn: api.connectors });
export const useMcp = () => useQuery({ queryKey: qk.mcp, queryFn: api.mcp });
export const useSkills = () => useQuery({ queryKey: qk.skills, queryFn: api.skills });
export const useSchedules = () => useQuery({ queryKey: qk.schedules, queryFn: api.schedules });
export const useRuns = (f: RunFilters = {}, refetchMs?: number | false) =>
  useQuery({ queryKey: qk.runs(f), queryFn: () => api.runs(f), refetchInterval: refetchMs || false });
export const useRun = (id: string) => useQuery({ queryKey: qk.run(id), queryFn: () => api.run(id) });
export const useMemories = (f: MemoryFilters) => useQuery({ queryKey: qk.memories(f), queryFn: () => api.memories(f) });
export const useActions = (status?: string) =>
  useQuery({ queryKey: qk.actions(status), queryFn: () => api.actions(status) });
export const useConversations = () => useQuery({ queryKey: qk.conversations, queryFn: api.conversations });
export const useStats = (days: number) => useQuery({ queryKey: qk.stats(days), queryFn: () => api.stats(days) });

/** Invalidate queries by key prefix. */
export function invalidate(qc: QueryClient, ...keys: string[]) {
  for (const k of keys) void qc.invalidateQueries({ queryKey: [k] });
}

/** Subscribes to the global /api/events stream and keeps caches fresh. Mount once at the app root. */
export function useGlobalEvents(): void {
  const qc = useQueryClient();
  useSSE<GlobalEvent>(api.globalEventsUrl, {
    onEvent: (ev) => {
      switch (ev.type) {
        case "status":
          if (ev.status) qc.setQueryData<Status>(qk.status, ev.status);
          break;
        case "run_queued":
        case "run_started":
        case "run_finished":
          invalidate(qc, "runs", "status");
          if (ev.run?.id) void qc.invalidateQueries({ queryKey: qk.run(ev.run.id) });
          invalidate(qc, "stats", "schedules");
          break;
        case "schedule_fired":
          invalidate(qc, "schedules", "runs", "status");
          break;
        case "action_pending":
        case "action_decided":
          invalidate(qc, "actions", "status");
          if (ev.type === "action_decided") invalidate(qc, "schedules", "agents", "skills", "memories");
          break;
      }
    },
  });
  // Fallback if SSE is blocked: status polling is already on a 15 s interval.
}

export function useInvalidatingMutation<TVars, TData>(fn: (v: TVars) => Promise<TData>, keys: string[]) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => invalidate(qc, ...keys) });
}

/** Re-render every `ms` while `active` (for elapsed timers / relative times). */
export function useTick(active = true, ms = 1000): number {
  const [, force] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(force, ms);
    return () => clearInterval(t);
  }, [active, ms, force]);
  return Date.now();
}

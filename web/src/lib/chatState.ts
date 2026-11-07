import type { ChatEvent, MessageStats, PendingAction } from "../api/types";

export interface ToolView { id: string; name: string; args?: unknown; ok?: boolean; result?: unknown; done: boolean }
export interface LiveMsg {
  key: string; reasoning: string; content: string; tools: ToolView[]; actions: PendingAction[];
  runIds: string[]; stats: MessageStats | null; ended: boolean;
}
export interface LiveTurn { user: string | null; msgs: LiveMsg[]; error: string | null; streaming: boolean; seq: number }
export const emptyTurn: LiveTurn = { user: null, msgs: [], error: null, streaming: false, seq: 0 };

export type TurnAction =
  | { t: "start"; user: string }
  | { t: "ev"; ev: ChatEvent }
  | { t: "end"; error?: string | null }
  | { t: "clear" };

const blank = (key: string): LiveMsg => ({ key, reasoning: "", content: "", tools: [], actions: [], runIds: [], stats: null, ended: false });
const isEmpty = (m: LiveMsg) => !m.content && !m.reasoning && !m.tools.length && !m.actions.length && !m.runIds.length;

export function turnReducer(s: LiveTurn, a: TurnAction): LiveTurn {
  switch (a.t) {
    case "start":
      return { user: a.user, msgs: [], error: null, streaming: true, seq: 0 };
    case "clear":
      return emptyTurn;
    case "end":
      return { ...s, streaming: false, error: a.error ?? s.error };
    case "ev": {
      let seq = s.seq;
      let msgs = s.msgs;
      const ensure = (): LiveMsg => {
        const last = msgs[msgs.length - 1];
        if (last && !last.ended) return last;
        const m = blank(`live-${++seq}`);
        msgs = [...msgs, m];
        return m;
      };
      const upd = (fn: (m: LiveMsg) => LiveMsg) => {
        const cur = ensure();
        msgs = msgs.map((m) => (m === cur ? fn(m) : m));
      };
      const ev = a.ev;
      switch (ev.type) {
        case "message_start": {
          const last = msgs[msgs.length - 1];
          if (!(last && !last.ended && isEmpty(last))) msgs = [...msgs, blank(`live-${++seq}`)];
          break;
        }
        case "token":
          upd((m) => (ev.channel === "reasoning" ? { ...m, reasoning: m.reasoning + ev.text } : { ...m, content: m.content + ev.text }));
          break;
        case "tool_call":
          upd((m) =>
            m.tools.some((t) => t.id === (ev.id ?? ev.name)) ? m : { ...m, tools: [...m.tools, { id: ev.id ?? `${ev.name}-${m.tools.length}`, name: ev.name, args: ev.arguments, done: false }] },
          );
          break;
        case "tool_result":
          upd((m) => {
            const idx = m.tools.findIndex((t) => (ev.id ? t.id === ev.id : t.name === ev.name && !t.done));
            if (idx < 0) return { ...m, tools: [...m.tools, { id: ev.id ?? `r-${m.tools.length}`, name: ev.name ?? "tool", ok: ev.ok, result: ev.result, done: true }] };
            const tools = m.tools.slice();
            tools[idx] = { ...tools[idx], ok: ev.ok, result: ev.result, done: true };
            return { ...m, tools };
          });
          break;
        case "action_proposed":
          if (ev.action) upd((m) => (m.actions.some((x) => x.id === ev.action.id) ? m : { ...m, actions: [...m.actions, ev.action] }));
          break;
        case "run_started":
          upd((m) => (m.runIds.includes(ev.run_id) ? m : { ...m, runIds: [...m.runIds, ev.run_id] }));
          break;
        case "llm_end": {
          const { type: _t, ...stats } = ev;
          void _t;
          upd((m) => ({ ...m, stats }));
          break;
        }
        case "message_end":
          upd((m) => ({
            ...m, ended: true,
            content: ev.message?.content ?? m.content,
            reasoning: ev.message?.reasoning ?? m.reasoning,
            stats: ev.message?.stats ?? m.stats,
          }));
          break;
        case "error":
          return { ...s, msgs, seq, error: ev.detail ?? "The assistant returned an error." };
        case "done":
          return { ...s, msgs, seq, streaming: false };
      }
      return { ...s, msgs, seq };
    }
  }
}

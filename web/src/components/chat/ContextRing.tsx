import { useState } from "react";
import { api } from "../../api/client";
import { useContextUsage } from "../../api/hooks";
import { cn } from "../../lib/cn";
import { useToast } from "../ui/Toast";

const R = 7;
const C = 2 * Math.PI * R;
const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

/** Progress ring showing how much of the chat slot's context window the conversation uses. Click = compact now. */
export function ContextRing({ convId, thinking, effort, busy, onCompacted }: {
  convId: string | null; thinking: boolean; effort: string; busy?: boolean; onCompacted?: () => void;
}) {
  const q = useContextUsage(convId, { thinking, effort });
  const toast = useToast();
  const [working, setWorking] = useState(false);
  const u = q.data;
  const pct = u ? Math.min(u.pct, 1) : 0;
  const tone = pct >= 0.9 ? "text-err" : pct >= 0.7 ? "text-warn" : "text-accent";
  const compact = async () => {
    if (!convId || busy || working) return;
    setWorking(true);
    try {
      const r = await api.compactConversation(convId, { thinking, effort });
      toast.success(r.summary_failed ? "Dropped old tool output; summarising failed" : r.summarised ? `Summarised ${r.summarised} messages` : r.pruned ? "Dropped old tool output" : "Nothing to compact yet");
      onCompacted?.();
    } catch (e) {
      toast.error(`Could not compact: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setWorking(false);
    }
  };
  const title = u
    ? `Context: ${u.exact ? "" : "~"}${fmt(u.used)} of ${fmt(u.budget)} tokens (${Math.round(u.pct * 100)}%)\n` +
      `Window ${fmt(u.limit)} (${u.source === "server" ? "from llama-server" : "from settings"}) minus ${fmt(u.reserve)} reserved for the reply.\n` +
      (u.summarised_messages ? `${u.summarised_messages} older messages are replaced by a summary.\n` : "") +
      (busy ? "" : "Click to summarise older messages now.")
    : "Context usage";
  return (
    <button type="button" onClick={() => void compact()} disabled={!u || busy || working}
      className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface2 disabled:hover:bg-transparent"
      title={title} data-testid="context-ring" aria-label={u ? `Context ${Math.round(u.pct * 100)}% full. Compact now` : "Context usage"}>
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden className={cn("-rotate-90", working && "animate-pulse")}>
        <circle cx="9" cy="9" r={R} fill="none" stroke="currentColor" strokeWidth="2.5" className="text-line" />
        {u && <circle cx="9" cy="9" r={R} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - pct)} className={cn("transition-[stroke-dashoffset]", tone)} />}
      </svg>
      {working ? "…" : u ? `${Math.round(u.pct * 100)}%` : "–"}
    </button>
  );
}

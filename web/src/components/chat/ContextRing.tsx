import { useContextUsage } from "../../api/hooks";
import { cn } from "../../lib/cn";

const R = 7;
const C = 2 * Math.PI * R;
const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

/** Small progress ring showing how much of the chat slot's context window the conversation uses. */
export function ContextRing({ convId, thinking, effort }: { convId: string | null; thinking: boolean; effort: string }) {
  const q = useContextUsage(convId, { thinking, effort });
  const u = q.data;
  const pct = u ? Math.min(u.pct, 1) : 0;
  const tone = pct >= 0.9 ? "text-err" : pct >= 0.7 ? "text-warn" : "text-accent";
  const title = u
    ? `Context: ${u.exact ? "" : "~"}${fmt(u.used)} of ${fmt(u.budget)} tokens (${Math.round(u.pct * 100)}%)\n` +
      `Window ${fmt(u.limit)} (${u.source === "server" ? "from llama-server" : "from settings"}) minus ${fmt(u.reserve)} reserved for the reply.\n` +
      `Only the newest ${u.history_messages} messages are sent.` +
      (pct >= 0.9 ? "\nAlmost full: start a new chat soon." : "")
    : "Context usage";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted" title={title} data-testid="context-ring" aria-label={u ? `Context ${Math.round(u.pct * 100)}% full` : "Context usage"}>
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden className="-rotate-90">
        <circle cx="9" cy="9" r={R} fill="none" stroke="currentColor" strokeWidth="2.5" className="text-line" />
        {u && <circle cx="9" cy="9" r={R} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - pct)} className={cn("transition-[stroke-dashoffset]", tone)} />}
      </svg>
      {u ? `${Math.round(u.pct * 100)}%` : "–"}
    </span>
  );
}

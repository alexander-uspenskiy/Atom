import { Link } from "react-router-dom";
import { Calendar, MessageSquare, Play, Webhook } from "lucide-react";
import type { RunSummary } from "../api/types";
import { StatusBadge } from "./ui/Badge";
import { fmtDuration, fmtRelative, fmtTokens, truncate } from "../lib/format";

const trigIcon = { manual: Play, schedule: Calendar, chat: MessageSquare, api: Webhook } as const;

export function TriggerIcon({ trigger }: { trigger?: string }) {
  const I = trigIcon[(trigger ?? "manual") as keyof typeof trigIcon] ?? Play;
  return <I className="h-3.5 w-3.5 shrink-0 text-muted" aria-label={trigger ?? "manual"} />;
}

/** One compact row for a run, used in recent-runs lists. */
export function RunRow({ run }: { run: RunSummary }) {
  return (
    <Link
      to={`/runs/${encodeURIComponent(run.id)}`}
      className="flex items-center gap-2 border-b border-line px-3 py-2 last:border-0 hover:bg-surface2"
    >
      <TriggerIcon trigger={run.trigger} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{truncate(run.task, 110) || run.id}</div>
        <div className="truncate text-xs text-muted">
          {run.agent_name ?? "—"} · {fmtRelative(run.finished_at ?? run.started_at ?? run.queued_at)} · {run.steps ?? 0} steps ·{" "}
          {fmtTokens(run.prompt_tokens)} in / {fmtTokens(run.completion_tokens)} out
        </div>
      </div>
      <span className="hidden text-xs tabular-nums text-muted sm:inline">{fmtDuration(run.wall_seconds)}</span>
      <StatusBadge status={run.status} success={run.success} />
    </Link>
  );
}

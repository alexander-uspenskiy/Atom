import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { History } from "lucide-react";
import { useAgents, useRuns } from "../api/hooks";
import { Page } from "../components/Page";
import { TriggerIcon } from "../components/RunRow";
import { StatusBadge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { SearchInput } from "../components/ui/Fields";
import { Select } from "../components/ui/Select";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { cachedPct, fmtDateTime, fmtDuration, fmtPct, fmtRelative, fmtTokens, truncate } from "../lib/format";

const PAGE = 25;
const STATUSES = ["", "queued", "running", "done", "failed", "budget", "stopped"];

export default function RunsPage() {
  const [sp] = useSearchParams();
  const [status, setStatus] = useState(sp.get("status") ?? "");
  const [agent, setAgent] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const agents = useAgents();
  const runs = useRuns({ status, agent_id: agent, q, limit: PAGE, offset });
  const total = runs.data?.total ?? 0;
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setOffset(0);
  };

  return (
    <Page
      title="Runs"
      subtitle={runs.data ? `${total} run${total === 1 ? "" : "s"}` : undefined}
      actions={
        <>
          <SearchInput className="w-52" value={q} onChange={reset(setQ)} placeholder="Search tasks…" />
          <Select aria-label="Status" className="w-32" value={status} onChange={(e) => reset(setStatus)(e.target.value)} options={STATUSES.map((s) => ({ value: s, label: s || "All statuses" }))} />
          <Select
            aria-label="Agent"
            className="w-40"
            value={agent}
            onChange={(e) => reset(setAgent)(e.target.value)}
            options={[{ value: "", label: "All agents" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))]}
          />
        </>
      }
    >
      <Card className="overflow-hidden">
        {runs.isLoading && <Loading />}
        {runs.error && !runs.data && <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />}
        {runs.data && runs.data.items.length === 0 && (
          <EmptyState icon={History} title="No runs found" hint={status || agent || q ? "Try clearing the filters." : "Runs appear here once an agent is started."} />
        )}
        {runs.data && runs.data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="border-b border-line bg-surface2/60 text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Task</th>
                  <th className="px-2 py-1.5 font-medium">Agent</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 text-right font-medium">Steps</th>
                  <th className="px-2 py-1.5 text-right font-medium">In / out</th>
                  <th className="px-2 py-1.5 text-right font-medium">Cached</th>
                  <th className="px-2 py-1.5 text-right font-medium">Time</th>
                  <th className="px-3 py-1.5 font-medium">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((r) => (
                  <tr key={r.id} className="border-b border-line last:border-0 hover:bg-surface2/60">
                    <td className="max-w-[26rem] px-3 py-1.5">
                      <Link to={`/runs/${encodeURIComponent(r.id)}`} className="flex items-center gap-2 hover:text-accent">
                        <TriggerIcon trigger={r.trigger} />
                        <span className="truncate">{truncate(r.task, 100) || r.id}</span>
                      </Link>
                    </td>
                    <td className="px-2 py-1.5 text-muted">{r.agent_name ?? "—"}</td>
                    <td className="px-2 py-1.5"><StatusBadge status={r.status} success={r.success} /></td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.steps ?? 0}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtTokens(r.prompt_tokens)} / {fmtTokens(r.completion_tokens)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(cachedPct(r.cached_tokens, r.prompt_tokens))}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtDuration(r.wall_seconds)}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-muted" title={fmtDateTime(r.started_at ?? r.queued_at)}>{fmtRelative(r.started_at ?? r.queued_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {total > PAGE && (
        <div className="mt-3 flex items-center justify-between text-xs text-muted">
          <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <div className="flex gap-2">
            <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</Button>
            <Button size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
          </div>
        </div>
      )}
    </Page>
  );
}

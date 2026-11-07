import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, CalendarClock, Cpu, Layers, Send, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "../api/client";
import { useRuns, useSchedules, useStatus, useTick } from "../api/hooks";
import type { RunSummary } from "../api/types";
import { Page } from "../components/Page";
import { RunRow } from "../components/RunRow";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardHeader, Stat } from "../components/ui/Card";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { useToast } from "../components/ui/Toast";
import { describeTrigger } from "../lib/schedule";
import { errMsg, fmtDateTime, fmtDuration, fmtRelative, truncate } from "../lib/format";

function RunningCard({ run }: { run: RunSummary }) {
  useTick(true, 1000);
  const t0 = run.started_at ?? run.queued_at;
  return (
    <Link to={`/runs/${encodeURIComponent(run.id)}`} className="block border-b border-line px-3 py-2 last:border-0 hover:bg-surface2">
      <div className="flex items-center gap-2">
        <StatusBadge status={run.status} />
        <span className="min-w-0 flex-1 truncate text-sm">{truncate(run.task, 120)}</span>
        <span className="text-xs tabular-nums text-muted">{t0 ? fmtDuration(Date.now() / 1000 - t0) : "–"}</span>
      </div>
      <div className="mt-1 flex items-center gap-3 text-xs text-muted">
        <span>{run.agent_name ?? "—"}</span>
        <span>{run.steps ?? 0} steps</span>
        {run.current_url && <span className="truncate">{run.current_url}</span>}
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded bg-surface2" aria-hidden>
        <div className="h-full w-1/3 animate-pulseDot rounded bg-info" />
      </div>
    </Link>
  );
}

export default function OverviewPage() {
  const nav = useNavigate();
  const toast = useToast();
  const status = useStatus();
  const running = useRuns({ status: "running", limit: 10 });
  const queued = useRuns({ status: "queued", limit: 10 });
  const recent = useRuns({ limit: 8 });
  const schedules = useSchedules();
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState(false);

  const s = status.data;
  const llm = s?.llm;
  const slots = llm?.slots ?? [];
  const activeRuns = [...(running.data?.items ?? []), ...(queued.data?.items ?? [])];
  const upcoming = (schedules.data ?? [])
    .filter((x) => x.enabled && x.next_run_at)
    .sort((a, b) => (a.next_run_at ?? 0) - (b.next_run_at ?? 0))
    .slice(0, 5);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const text = ask.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const c = await api.createConversation(null);
      nav(`/chat?c=${encodeURIComponent(c.id)}`, { state: { send: text } });
    } catch (err) {
      toast.error(`Could not start chat: ${errMsg(err)}`);
      setBusy(false);
    }
  };

  return (
    <Page title="Overview" subtitle="Mission control for your local agents">
      <div className="mx-auto max-w-6xl space-y-4">
        {status.error && !s && <Card><ErrorState error={status.error} onRetry={() => void status.refetch()} /></Card>}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="LLM"
            icon={<Cpu className="h-4 w-4" />}
            tone={llm?.healthy === true ? "ok" : llm?.healthy === false ? "err" : undefined}
            value={status.isLoading ? "…" : llm?.healthy ? "Healthy" : llm ? "Down" : "Unknown"}
            sub={`${llm?.model ?? "—"} · ${slots.filter((x) => x.busy).length}/${slots.length} busy`}
          />
          <Stat
            label="Runs"
            icon={<Activity className="h-4 w-4" />}
            value={`${s?.runs?.running?.length ?? 0} running`}
            sub={`${s?.runs?.queued ?? 0} queued · max ${s?.runs?.max_concurrent ?? "?"} concurrent`}
          />
          <Stat
            label="Scheduler"
            icon={<CalendarClock className="h-4 w-4" />}
            value={s?.scheduler?.running === false ? "Stopped" : `${s?.scheduler?.jobs ?? 0} ${(s?.scheduler?.jobs ?? 0) === 1 ? "job" : "jobs"}`}
            tone={s?.scheduler?.running === false ? "warn" : undefined}
            sub={s?.scheduler?.running ? "scheduler running" : s?.scheduler ? "scheduler not running" : "—"}
          />
          <Link to="/approvals" className="block rounded-lg focus-visible:outline-offset-2">
            <Stat
              label="Pending approvals"
              icon={<ShieldCheck className="h-4 w-4" />}
              value={String(s?.pending_actions ?? 0)}
              tone={(s?.pending_actions ?? 0) > 0 ? "warn" : undefined}
              sub={(s?.pending_actions ?? 0) > 0 ? "Review now →" : "all clear"}
            />
          </Link>
        </div>

        <Card>
          <form onSubmit={(e) => void submit(e)} className="flex items-center gap-2 p-2.5">
            <Sparkles className="ml-1 h-4 w-4 shrink-0 text-accent" aria-hidden />
            <input
              aria-label="Quick ask"
              className="input flex-1"
              placeholder="Quick ask — e.g. “Every morning at 8, summarize Hacker News”"
              value={ask}
              onChange={(e) => setAsk(e.target.value)}
              disabled={busy}
            />
            <Button type="submit" variant="primary" icon={<Send className="h-3.5 w-3.5" />} loading={busy} disabled={!ask.trim()}>Ask</Button>
          </form>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title="Running now" icon={<Layers className="h-3.5 w-3.5" />} actions={<Link to="/runs?status=running" className="text-xs text-accent hover:underline">All runs</Link>} />
            {(running.isLoading || queued.isLoading) && <Loading />}
            {running.error && <ErrorState error={running.error} onRetry={() => void running.refetch()} />}
            {!running.isLoading && !running.error && activeRuns.length === 0 && <EmptyState title="No active runs" hint="Start an agent from the Agents page or ask the assistant." />}
            {activeRuns.map((r) => <RunningCard key={r.id} run={r} />)}
          </Card>

          <Card>
            <CardHeader title="Upcoming schedules" icon={<CalendarClock className="h-3.5 w-3.5" />} actions={<Link to="/schedules" className="text-xs text-accent hover:underline">Manage</Link>} />
            {schedules.isLoading && <Loading />}
            {schedules.error && <ErrorState error={schedules.error} onRetry={() => void schedules.refetch()} />}
            {schedules.data && upcoming.length === 0 && <EmptyState title="Nothing scheduled" hint="Create a schedule to run an agent automatically." />}
            {upcoming.map((x) => (
              <div key={x.id} className="flex items-center gap-2 border-b border-line px-3 py-2 last:border-0">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{x.name}</div>
                  <div className="truncate text-xs text-muted">{x.agent_name ?? "—"} · {describeTrigger(x.trigger)}</div>
                </div>
                <div className="text-right text-xs">
                  <div className="font-medium">{fmtRelative(x.next_run_at)}</div>
                  <div className="text-muted">{fmtDateTime(x.next_run_at)}</div>
                </div>
                {x.created_by === "assistant" && <Badge tone="accent">assistant</Badge>}
              </div>
            ))}
          </Card>
        </div>

        <Card>
          <CardHeader title="Recent runs" actions={<Link to="/runs" className="text-xs text-accent hover:underline">View all</Link>} />
          {recent.isLoading && <Loading />}
          {recent.error && <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />}
          {recent.data && recent.data.items.length === 0 && <EmptyState title="No runs yet" />}
          {recent.data?.items.map((r) => <RunRow key={r.id} run={r} />)}
        </Card>
      </div>
    </Page>
  );
}

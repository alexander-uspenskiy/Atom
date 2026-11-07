import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowUp, Download, ExternalLink, Image as ImageIcon, Square, Timer, Wifi, WifiOff } from "lucide-react";
import { api } from "../api/client";
import { qk, useRun, useTick } from "../api/hooks";
import { useRunStream } from "../hooks/useRunStream";
import { isActive, stepsToItems } from "../lib/runState";
import { Page } from "../components/Page";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";
import { Dialog } from "../components/ui/Dialog";
import { JsonBlock } from "../components/ui/CodeBlock";
import { Markdown } from "../components/ui/Markdown";
import { ErrorState, Loading } from "../components/ui/Spinner";
import { useToast } from "../components/ui/Toast";
import { NowPanel } from "../components/run/NowPanel";
import { Timeline } from "../components/run/Timeline";
import { ImageGrid } from "../components/chat/Attachments";
import { cachedPct, errMsg, fmtDateTime, fmtDuration, fmtPct, fmtTokens, hostOf } from "../lib/format";

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-[6.5rem] flex-1 px-3 py-1.5">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="text-base font-semibold tabular-nums leading-tight">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function ResultView({ text }: { text: string }) {
  try {
    const j: unknown = JSON.parse(text);
    if (j && typeof j === "object") return <JsonBlock value={j} maxHeight="20rem" className="!my-0" />;
  } catch {
    /* plain text */
  }
  return <Markdown text={text} />;
}

export default function RunPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const detail = useRun(id);
  const run = detail.data?.run;
  const active = isActive(run?.status);
  const { state: live, conn, dupes } = useRunStream(id, !!run && active, () => {
    void qc.invalidateQueries({ queryKey: qk.run(id) });
    void qc.invalidateQueries({ queryKey: ["runs"] });
  });
  const [zoom, setZoom] = useState<number | null>(null);
  const [orderOverride, setOrderOverride] = useState<boolean | null>(null);
  useTick(active || live.status === "running", 1000);

  const stop = useMutation({
    mutationFn: () => api.stopRun(id),
    onSuccess: () => {
      toast.success("Stop requested");
      void qc.invalidateQueries({ queryKey: qk.run(id) });
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const items = useMemo(() => (active ? live.items : stepsToItems(detail.data?.steps)), [active, live.items, detail.data?.steps]);

  if (detail.isLoading) return <Page title="Run"><Loading /></Page>;
  if (detail.error || !run) {
    return (
      <Page title="Run">
        <ErrorState error={detail.error ?? new Error("Run not found")} onRetry={() => void detail.refetch()} />
      </Page>
    );
  }

  const status = live.finished?.status ?? (active ? (live.status ?? run.status) : run.status);
  const running = isActive(status);
  const t0 = run.started_at ?? run.queued_at ?? live.firstTs ?? null;
  const elapsed = running
    ? t0 ? Date.now() / 1000 - t0 : null
    : run.wall_seconds ?? (run.finished_at && t0 ? run.finished_at - t0 : null);

  // Totals: live accumulators while streaming (never lower than the stored summary), summary afterwards.
  const useLive = active && live.totals.steps > 0;
  const prompt = useLive ? Math.max(live.totals.prompt, run.prompt_tokens ?? 0) : (run.prompt_tokens ?? 0);
  const cached = useLive ? Math.max(live.totals.cached, run.cached_tokens ?? 0) : (run.cached_tokens ?? 0);
  const completion = useLive ? Math.max(live.totals.completion, run.completion_tokens ?? 0) : (run.completion_tokens ?? 0);
  const llmS = useLive ? Math.max(live.totals.llm, run.llm_seconds ?? 0) : (run.llm_seconds ?? 0);
  const toolS = useLive ? Math.max(live.totals.tool, run.tool_seconds ?? 0) : (run.tool_seconds ?? 0);
  const steps = useLive ? Math.max(live.totals.steps, run.steps ?? 0) : (run.steps ?? items.filter((i) => i.kind === "llm").length);

  const shotN = live.shot?.n ?? run.last_screenshot ?? null;
  const url = live.currentUrl ?? run.current_url ?? null;
  const newestFirst = orderOverride ?? running;
  const result = live.finished?.result ?? run.result;
  const error = live.finished?.error ?? run.error;

  return (
    <Page
      title={
        <span className="flex items-center gap-2">
          <Link to="/runs" aria-label="Back to runs" className="text-muted hover:text-fg"><ArrowLeft className="h-4 w-4" /></Link>
          <span className="truncate">{run.task || run.id}</span>
        </span>
      }
      subtitle={
        <span>
          {run.agent_name ?? "—"} · {run.trigger ?? "manual"} · <span className="font-mono">{run.id}</span>
          {run.thinking ? ` · thinking ${run.thinking}` : ""}{run.effort ? ` · effort ${run.effort}` : ""}
        </span>
      }
      actions={
        <>
          <span
            className="inline-flex items-center gap-1 text-xs text-muted"
            data-testid="conn"
            data-conn={conn}
            data-dupes={dupes}
            title={dupes ? `${dupes} replayed duplicate events ignored` : undefined}
          >
            {running && (conn === "live" ? <Wifi className="h-3.5 w-3.5 text-ok" /> : <WifiOff className="h-3.5 w-3.5 text-warn" />)}
            {running && (conn === "live" ? "live" : conn === "reconnecting" ? "reconnecting…" : "connecting…")}
          </span>
          <StatusBadge status={status} success={live.finished?.success ?? run.success} />
          <span className="inline-flex items-center gap-1 text-sm tabular-nums" data-testid="elapsed" title="Elapsed">
            <Timer className="h-3.5 w-3.5 text-muted" /> {fmtDuration(elapsed)}
          </span>
          {!running && (
            <a href={api.traceUrl(run.id)} className="inline-flex h-7 items-center gap-1 rounded-md border border-line px-2 text-xs hover:bg-surface2" download>
              <Download className="h-3.5 w-3.5" /> Trace
            </a>
          )}
          {running && (
            <Button variant="danger" size="sm" icon={<Square className="h-3.5 w-3.5" />} loading={stop.isPending} onClick={() => stop.mutate()}>
              Stop
            </Button>
          )}
        </>
      }
    >
      <div className="mx-auto max-w-[1500px] space-y-3">
        {run.images && run.images.length > 0 && (
          <Card>
            <CardHeader title={`Attached images (${run.images.length})`} icon={<ImageIcon className="h-3.5 w-3.5" />} />
            <div className="p-2"><ImageGrid ids={run.images} size="sm" /></div>
          </Card>
        )}
        <Card className="flex flex-wrap divide-x divide-line">
          <Kpi label="Input tokens" value={fmtTokens(prompt)} />
          <Kpi label="Cached" value={fmtPct(cachedPct(cached, prompt))} sub={`${fmtTokens(cached)} tokens`} />
          <Kpi label="Output tokens" value={fmtTokens(completion)} />
          <Kpi label="LLM time" value={fmtDuration(llmS)} />
          <Kpi label="Tool time" value={fmtDuration(toolS)} />
          <Kpi label="Steps" value={String(steps)} />
        </Card>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 space-y-3">
            {running ? (
              <NowPanel now={live.now} tool={live.tool} active={running} />
            ) : (
              <Card>
                <CardHeader title={error ? "Error" : "Result"} actions={run.success === false ? <Badge tone="warn">unsuccessful</Badge> : undefined} />
                <div className="px-3 py-2">
                  {error && <p className="mb-2 break-words text-sm text-err">{error}</p>}
                  {result ? <ResultView text={result} /> : !error && <p className="text-sm text-muted">No result was recorded.</p>}
                </div>
              </Card>
            )}

            <Card>
              <CardHeader
                title={`Timeline (${items.length})`}
                actions={
                  <Button size="sm" variant="ghost" icon={newestFirst ? <ArrowDown className="h-3.5 w-3.5" /> : <ArrowUp className="h-3.5 w-3.5" />} onClick={() => setOrderOverride(!newestFirst)}>
                    {newestFirst ? "Newest first" : "Oldest first"}
                  </Button>
                }
              />
              <div className="p-2">
                {items.length === 0 ? (
                  <p className="px-2 py-6 text-center text-sm text-muted">
                    {running ? (run.status === "queued" ? "Queued — waiting for a free slot…" : "Waiting for the first step…") : "No steps were recorded."}
                  </p>
                ) : (
                  <Timeline items={items} runId={run.id} newestFirst={newestFirst} onShot={setZoom} />
                )}
              </div>
            </Card>
          </div>

          <div className="min-w-0 space-y-3">
            <Card>
              <CardHeader title="Browser" icon={<ImageIcon className="h-3.5 w-3.5" />} actions={shotN != null ? <Badge>#{shotN}</Badge> : undefined} />
              <div className="p-2">
                {shotN != null ? (
                  <button type="button" onClick={() => setZoom(shotN)} className="block w-full overflow-hidden rounded border border-line" aria-label="Enlarge latest screenshot">
                    <img key={shotN} src={api.shotUrl(run.id, shotN)} alt={live.shot?.title ?? "Latest browser screenshot"} className="w-full" data-testid="latest-shot" />
                  </button>
                ) : (
                  <p className="px-2 py-8 text-center text-sm text-muted">No screenshots yet.</p>
                )}
                {(url || live.shot?.title) && (
                  <div className="mt-1.5 min-w-0 text-xs">
                    {live.shot?.title && <div className="truncate font-medium">{live.shot.title}</div>}
                    {url && (
                      <a href={url} target="_blank" rel="noreferrer noopener" className="inline-flex max-w-full items-center gap-1 text-muted hover:text-accent">
                        <ExternalLink className="h-3 w-3 shrink-0" /> <span className="truncate">{hostOf(url)}</span>
                      </a>
                    )}
                  </div>
                )}
              </div>
            </Card>

            <Card>
              <CardHeader title="Details" />
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 py-2 text-xs">
                <dt className="text-muted">Queued</dt><dd>{fmtDateTime(run.queued_at)}</dd>
                <dt className="text-muted">Started</dt><dd>{fmtDateTime(run.started_at)}</dd>
                <dt className="text-muted">Finished</dt><dd>{fmtDateTime(run.finished_at)}</dd>
                <dt className="text-muted">Processed</dt><dd>{fmtTokens(run.processed_tokens)} tokens evaluated</dd>
                {run.schedule_id && (<><dt className="text-muted">Schedule</dt><dd><Link className="text-accent hover:underline" to="/schedules">{run.schedule_id}</Link></dd></>)}
              </dl>
            </Card>
          </div>
        </div>
      </div>

      <Dialog open={zoom !== null} onClose={() => setZoom(null)} title={`Screenshot ${zoom ?? ""}`} wide>
        {zoom !== null && <img src={api.shotUrl(run.id, zoom)} alt={`Screenshot ${zoom}`} className="w-full rounded border border-line" />}
      </Dialog>
    </Page>
  );
}

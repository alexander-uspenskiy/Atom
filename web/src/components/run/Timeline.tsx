import { useState } from "react";
import { Brain, ChevronRight, Image as ImageIcon, Layers, Loader2, StickyNote, Wrench } from "lucide-react";
import type { TItem } from "../../lib/runState";
import { Badge } from "../ui/Badge";
import { CodeBlock, JsonBlock } from "../ui/CodeBlock";
import { api } from "../../api/client";
import { argsPreview, cachedPct, fmtDuration, fmtMs, fmtPct, fmtTokens, fmtTps, prettyJSON } from "../../lib/format";
import { cn } from "../../lib/cn";

function Metric({ k, v }: { k: string; v: string }) {
  return (
    <span className="whitespace-nowrap">
      <span className="text-muted">{k} </span>
      <span className="tabular-nums">{v}</span>
    </span>
  );
}

function LlmMetrics({ it }: { it: TItem }) {
  if (it.running) return <span className="text-xs text-info">generating…</span>;
  const pct = cachedPct(it.cached_tokens, it.prompt_tokens);
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
      <Metric k="in" v={`${fmtTokens(it.prompt_tokens)}${pct !== null ? ` (${fmtPct(pct)} cached)` : ""}`} />
      <Metric k="out" v={fmtTokens(it.completion_tokens)} />
      <Metric k="prefill" v={fmtMs(it.prefill_ms)} />
      <Metric k="decode" v={fmtMs(it.decode_ms)} />
      <Metric k="speed" v={fmtTps(it.decode_tps)} />
    </div>
  );
}

function ItemCard({ it, runId, onShot, defaultOpen }: { it: TItem; runId: string; onShot: (n: number) => void; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const isLlm = it.kind === "llm";
  const Icon = isLlm ? Brain : it.kind === "tool" ? Wrench : it.kind === "compact" ? Layers : StickyNote;
  const hasBody = !!(it.reasoning || it.content || it.result || it.args || it.toolCalls?.length || it.screenshot != null || it.url);
  const preview = isLlm
    ? it.toolCalls?.length ? `→ ${it.toolCalls.map((t) => t.name).join(", ")}` : (it.content ?? "").replace(/\s+/g, " ").slice(0, 100)
    : argsPreview(it.args, 110);

  return (
    <li className={cn("rounded-md border border-line bg-surface", it.ok === false && "border-err/40")} data-testid="timeline-item" data-id={it.id}>
      <button
        type="button"
        className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left"
        aria-expanded={open}
        onClick={() => hasBody && setOpen((o) => !o)}
        disabled={!hasBody}
      >
        <ChevronRight className={cn("mt-1 h-3.5 w-3.5 shrink-0 text-muted transition-transform", open && "rotate-90", !hasBody && "invisible")} aria-hidden />
        <span className={cn("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded", isLlm ? "bg-accent/10 text-accent" : "bg-info/10 text-info")}>
          {it.running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Icon className="h-3 w-3" aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={cn("text-sm font-semibold", !isLlm && "font-mono")}>{isLlm ? `LLM call${it.step != null ? ` #${it.step}` : ""}` : it.name}</span>
            {isLlm && it.think && <Badge tone="accent">thinking</Badge>}
            {it.kind === "tool" && !it.running && it.ok != null && <Badge tone={it.ok ? "ok" : "err"}>{it.ok ? "ok" : "error"}</Badge>}
            {it.kind === "tool" && it.running && <Badge tone="info" dot pulse>running</Badge>}
            {it.kind === "tool" && it.tool_seconds != null && <span className="text-xs tabular-nums text-muted">{fmtDuration(it.tool_seconds)}</span>}
            {it.screenshot != null && <ImageIcon className="h-3 w-3 text-muted" aria-label="has screenshot" />}
          </div>
          {preview && <div className="truncate font-mono text-xs text-muted">{preview}</div>}
          {isLlm && <LlmMetrics it={it} />}
        </div>
      </button>
      {open && (
        <div className="space-y-2 border-t border-line px-3 py-2">
          {it.reasoning && (
            <div>
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Reasoning</div>
              <p className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-mono text-xs italic text-muted">{it.reasoning}</p>
            </div>
          )}
          {isLlm && it.content && (
            <div>
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Response</div>
              <p className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-mono text-xs">{it.content}</p>
            </div>
          )}
          {it.toolCalls && it.toolCalls.length > 0 && (
            <div>
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Tool calls</div>
              {it.toolCalls.map((t, i) => (
                <div key={t.id ?? i} className="font-mono text-xs"><b>{t.name}</b> <span className="text-muted">{argsPreview(t.arguments, 200)}</span></div>
              ))}
            </div>
          )}
          {!isLlm && it.args !== undefined && it.args !== null && Object.keys(it.args as object).length > 0 && (
            <div>
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Arguments</div>
              <JsonBlock value={it.args} maxHeight="10rem" className="!my-0" />
            </div>
          )}
          {it.result && (
            <div>
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Result preview</div>
              <CodeBlock code={typeof it.result === "string" ? it.result : prettyJSON(it.result)} maxHeight="14rem" className="!my-0" />
            </div>
          )}
          {it.url && <div className="truncate text-xs text-muted">URL: {it.url}</div>}
          {it.screenshot != null && (
            <button type="button" onClick={() => onShot(it.screenshot as number)} className="block overflow-hidden rounded border border-line" aria-label="Enlarge screenshot">
              <img src={api.shotUrl(runId, it.screenshot)} alt={`Screenshot ${it.screenshot}`} loading="lazy" className="h-24 w-auto" />
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function Timeline({
  items, runId, newestFirst, onShot,
}: { items: TItem[]; runId: string; newestFirst: boolean; onShot: (n: number) => void }) {
  const list = newestFirst ? [...items].reverse() : items;
  return (
    <ol className="space-y-1.5" aria-label="Step timeline">
      {list.map((it) => (
        <ItemCard key={it.id} it={it} runId={runId} onShot={onShot} />
      ))}
    </ol>
  );
}

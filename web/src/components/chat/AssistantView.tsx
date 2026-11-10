import { useState } from "react";
import { Brain, ChevronRight, Play, Wrench } from "lucide-react";
import { Link } from "react-router-dom";
import type { MessageStats, PendingAction } from "../../api/types";
import type { ToolView } from "../../lib/chatState";
import { api } from "../../api/client";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { CodeBlock } from "../ui/CodeBlock";
import { Markdown } from "../ui/Markdown";
import { ApprovalCard } from "../ApprovalCard";
import { argsPreview, fmtTokens, prettyJSON } from "../../lib/format";
import { cn } from "../../lib/cn";
import { MessageActions } from "./MessageActions";

export interface AsstView {
  key: string; reasoning: string; content: string; tools: ToolView[];
  actions: PendingAction[]; pendingActionIds: string[]; runIds: string[];
  stats?: MessageStats | null; streaming?: boolean;
  /** created_at (seconds) and the user prompt this reply answers, for the timestamp and "Run again" */
  at?: number; ask?: string;
}

/** "in 900 (600 cached) · out 80 · 9.2 s · 9.1 tok/s" */
export function statsLine(s?: MessageStats | null): string | null {
  if (!s) return null;
  const parts: string[] = [];
  if (s.prompt_tokens != null) parts.push(`in ${fmtTokens(s.prompt_tokens)} (${fmtTokens(s.cached_tokens ?? 0)} cached)`);
  if (s.completion_tokens != null) parts.push(`out ${fmtTokens(s.completion_tokens)}`);
  if (s.llm_seconds != null) parts.push(`${s.llm_seconds.toFixed(1)} s`);
  if (s.decode_tps != null) parts.push(`${s.decode_tps.toFixed(1)} tok/s`);
  return parts.length ? parts.join(" · ") : null;
}

function Reasoning({ text, live }: { text: string; live: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const isOpen = open ?? live;
  return (
    <div className="rounded-md border border-line/70 bg-surface2/50">
      <button type="button" className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-xs text-muted" aria-expanded={isOpen} onClick={() => setOpen(!isOpen)}>
        <ChevronRight className={cn("h-3 w-3 transition-transform", isOpen && "rotate-90")} aria-hidden />
        <Brain className={cn("h-3 w-3", live && "animate-pulseDot text-accent")} aria-hidden />
        {live ? "Thinking…" : "Reasoning"}
        <span className="text-muted/70">· {text.length.toLocaleString()} chars</span>
      </button>
      {isOpen && (
        <p className={cn("max-h-64 overflow-y-auto whitespace-pre-wrap break-words border-t border-line/70 px-3 py-2 font-mono text-xs italic leading-relaxed text-muted/90", live && "caret")}>
          {text}
        </p>
      )}
    </div>
  );
}

export function ToolCard({ t }: { t: ToolView }) {
  const [open, setOpen] = useState(false);
  const resultText = t.result === undefined || t.result === null ? "" : typeof t.result === "string" ? t.result : prettyJSON(t.result);
  return (
    <div className={cn("rounded-md border bg-surface", t.ok === false ? "border-err/40" : "border-line")} data-testid="tool-card">
      <button type="button" className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChevronRight className={cn("h-3 w-3 shrink-0 text-muted transition-transform", open && "rotate-90")} aria-hidden />
        <Wrench className="h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
        <span className="font-mono text-xs font-semibold">{t.name}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{argsPreview(t.args, 100)}</span>
        {t.approval === "pending" ? <Badge tone="warn" dot pulse>needs approval</Badge> : t.approval === "denied" ? <Badge tone="err">denied</Badge> : !t.done ? <Badge tone="info" dot pulse>running</Badge> : t.ok === false ? <Badge tone="err">error</Badge> : <Badge tone="ok">ok</Badge>}
      </button>
      {t.approval === "pending" && (
        <div className="flex items-center gap-2 border-t border-line px-3 py-2" role="group" aria-label="Approve tool call">
          <span className="flex-1 text-xs text-muted">Manual mode: run this?</span>
          <Button size="sm" variant="primary" onClick={() => void api.decideApproval(t.id, true).catch(() => undefined)}>Approve</Button>
          <Button size="sm" onClick={() => void api.decideApproval(t.id, false).catch(() => undefined)}>Deny</Button>
        </div>
      )}
      {open && (
        <div className="space-y-1 border-t border-line px-3 py-2">
          {t.args !== undefined && t.args !== null && <CodeBlock code={prettyJSON(t.args)} lang="args" maxHeight="10rem" className="!my-0" />}
          {resultText && <CodeBlock code={resultText} lang="result" maxHeight="14rem" className="!my-0" />}
        </div>
      )}
    </div>
  );
}

export function AssistantView({ v, onResend, busy }: { v: AsstView; onResend?: (text: string) => void; busy?: boolean }) {
  const stats = statsLine(v.stats);
  const blank = !v.content && !v.reasoning && !v.tools.length && !v.actions.length && !v.runIds.length && !v.pendingActionIds.length;
  return (
    <div className="flex gap-2.5" data-testid="assistant-msg">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent" aria-hidden>
        <Brain className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {v.reasoning && <Reasoning text={v.reasoning} live={!!v.streaming && !v.content} />}
        {v.tools.map((t) => <ToolCard key={t.id} t={t} />)}
        {v.content && (
          <div className={cn(v.streaming && "caret")}>
            <Markdown text={v.content} />
          </div>
        )}
        {blank && v.streaming && <p className="caret text-sm text-muted">Waiting for the model…</p>}
        {v.actions.map((a) => <ApprovalCard key={a.id} action={a} compact />)}
        {v.pendingActionIds.map((id) => (
          <div key={id} className="rounded-md border border-line px-3 py-2 text-xs text-muted">Proposed action <span className="font-mono">{id}</span> (details unavailable)</div>
        ))}
        {v.runIds.map((id) => (
          <Link key={id} to={`/runs/${encodeURIComponent(id)}`} className="flex items-center gap-2 rounded-md border border-info/40 bg-info/5 px-3 py-2 text-sm hover:bg-info/10">
            <Play className="h-4 w-4 text-info" aria-hidden />
            <span className="font-medium">Web agent run started</span>
            <span className="truncate font-mono text-xs text-muted">{id}</span>
            <span className="ml-auto text-xs text-info">Open live view →</span>
          </Link>
        ))}
        {stats && <div className="text-xs tabular-nums text-muted" data-testid="msg-stats">{stats}</div>}
        {!v.streaming && (v.content || v.at) && (
          <MessageActions at={v.at} text={v.content} onResend={v.ask && onResend ? () => onResend(v.ask as string) : undefined} disabled={busy}
            resendTitle="Ask the same question again" />
        )}
      </div>
    </div>
  );
}

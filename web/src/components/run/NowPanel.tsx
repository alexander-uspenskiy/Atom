import { useEffect, useRef } from "react";
import { Brain, Hourglass, MessageSquareText, Moon, Wrench } from "lucide-react";
import type { NowState, ToolNow } from "../../lib/runState";
import { Card, CardHeader } from "../ui/Card";
import { JsonBlock } from "../ui/CodeBlock";
import { cn } from "../../lib/cn";
import { fmtDuration } from "../../lib/format";
import { useTick } from "../../api/hooks";

const phaseInfo = {
  thinking: { label: "thinking…", icon: Brain, cls: "text-accent" },
  answering: { label: "answering", icon: MessageSquareText, cls: "text-ok" },
  waiting: { label: "reading prompt…", icon: Hourglass, cls: "text-info" },
  idle: { label: "idle", icon: Moon, cls: "text-muted" },
} as const;

export function NowPanel({ now, tool, active }: { now: NowState | null; tool: ToolNow | null; active: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const len = (now?.reasoning.length ?? 0) + (now?.content.length ?? 0);
  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [len, now?.step, now?.phase]);
  useTick(!!tool);

  const phase = !active ? "idle" : tool ? "idle" : (now?.phase ?? "waiting");
  const info = phaseInfo[phase];
  const Icon = info.icon;
  const empty = !now || (!now.reasoning && !now.content);

  return (
    <Card>
      <CardHeader
        title="Now"
        actions={
          <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", info.cls)} aria-live="polite" data-testid="phase">
            <Icon className={cn("h-3.5 w-3.5", active && phase !== "idle" && "animate-pulseDot")} aria-hidden />
            {tool ? "waiting for tool" : info.label}
            {now && active && <span className="font-normal text-muted">· step {now.step}{now.effort ? ` · effort ${now.effort}` : ""}{now.think ? " · think" : ""}</span>}
          </span>
        }
      />
      {tool && (
        <div className="border-b border-line bg-info/5 px-3 py-2">
          <div className="flex items-center gap-2 text-sm">
            <Wrench className="h-3.5 w-3.5 animate-pulseDot text-info" aria-hidden />
            <span className="text-xs text-muted">Executing tool</span>
            <span className="font-mono text-sm font-semibold">{tool.name}</span>
            <span className="ml-auto text-xs tabular-nums text-muted">{fmtDuration((Date.now() - tool.startedAt) / 1000)}</span>
          </div>
          {tool.args !== undefined && tool.args !== null && <JsonBlock value={tool.args} maxHeight="8rem" className="!mb-0" />}
        </div>
      )}
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="h-56 overflow-y-auto px-3 py-2 font-mono text-xs leading-relaxed"
        tabIndex={0}
        aria-label="Live model output"
      >
        {empty ? (
          <p className="text-muted">{active ? "Waiting for the model to produce tokens…" : "No live output."}</p>
        ) : (
          <>
            {now.reasoning && (
              <div className="mb-2">
                <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-accent/80">
                  <Brain className="h-3 w-3" aria-hidden /> reasoning
                </div>
                <p className={cn("whitespace-pre-wrap break-words italic text-muted", phase === "thinking" && "caret")}>{now.reasoning}</p>
              </div>
            )}
            {now.content && (
              <div>
                <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-ok/90">
                  <MessageSquareText className="h-3 w-3" aria-hidden /> answer
                </div>
                <p className={cn("whitespace-pre-wrap break-words", phase === "answering" && "caret")}>{now.content}</p>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

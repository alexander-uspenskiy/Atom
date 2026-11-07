import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import type { RunStatus } from "../../api/types";

export type Tone = "neutral" | "ok" | "warn" | "err" | "info" | "accent";
const tones: Record<Tone, string> = {
  neutral: "bg-surface2 text-muted border-line",
  ok: "bg-ok/10 text-ok border-ok/30",
  warn: "bg-warn/10 text-warn border-warn/30",
  err: "bg-err/10 text-err border-err/30",
  info: "bg-info/10 text-info border-info/30",
  accent: "bg-accent/10 text-accent border-accent/30",
};

export function Badge({
  tone = "neutral", children, className, dot, pulse,
}: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean; pulse?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-px text-[11px] font-medium leading-4",
        tones[tone],
        className,
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full bg-current", pulse && "animate-pulseDot")} aria-hidden />}
      {children}
    </span>
  );
}

const statusTone: Record<string, Tone> = {
  queued: "neutral", running: "info", done: "ok", failed: "err", budget: "warn", stopped: "neutral",
  pending: "warn", approved: "ok", rejected: "neutral",
};

export function StatusBadge({ status, success }: { status?: RunStatus | string | null; success?: boolean | null }) {
  const s = status ?? "unknown";
  let label: string = s;
  let tone: Tone = statusTone[s] ?? "neutral";
  if (s === "done" && success === false) {
    tone = "warn";
    label = "done (unsuccessful)";
  }
  return (
    <Badge tone={tone} dot pulse={s === "running" || s === "queued"}>
      {label}
    </Badge>
  );
}

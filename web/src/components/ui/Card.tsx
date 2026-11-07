import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border border-line bg-surface", className)} {...rest} />;
}

export function CardHeader({
  title, icon, actions, className,
}: { title: ReactNode; icon?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-h-[2.5rem] items-center justify-between gap-2 border-b border-line px-3 py-1.5", className)}>
      <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        {icon}
        {title}
      </h2>
      {actions && <div className="flex items-center gap-1.5">{actions}</div>}
    </div>
  );
}

export function Stat({
  label, value, sub, icon, tone,
}: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; tone?: "ok" | "err" | "warn" }) {
  return (
    <Card className="px-3 py-2.5">
      <div className="flex items-center justify-between text-xs text-muted">
        <span>{label}</span>
        {icon}
      </div>
      <div className={cn("mt-1 text-xl font-semibold tabular-nums leading-tight", tone === "ok" && "text-ok", tone === "err" && "text-err", tone === "warn" && "text-warn")}>{value}</div>
      {sub && <div className="mt-0.5 line-clamp-2 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

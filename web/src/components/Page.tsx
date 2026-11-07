import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export function Page({
  title, subtitle, actions, children, fill, className,
}: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; fill?: boolean; className?: string }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-[3rem] shrink-0 flex-wrap items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold leading-tight">{title}</h1>
          {subtitle && <p className="truncate text-xs text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={cn("min-h-0 flex-1", fill ? "overflow-hidden" : "overflow-y-auto p-4", className)}>{children}</div>
    </div>
  );
}

import { AlertTriangle, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Button } from "./Button";

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-muted", className)} role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label && <span className="text-sm">{label}</span>}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-10">
      <Spinner label={label} />
    </div>
  );
}

export function EmptyState({
  icon: Icon, title, hint, action, className,
}: { icon?: LucideIcon; title: string; hint?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-1.5 px-4 py-10 text-center", className)}>
      {Icon && <Icon className="h-7 w-7 text-muted/60" aria-hidden />}
      <div className="text-sm font-medium">{title}</div>
      {hint && <div className="max-w-sm text-xs text-muted">{hint}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error ?? "Something went wrong");
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-4 py-8 text-center">
      <AlertTriangle className="h-6 w-6 text-err" aria-hidden />
      <div className="text-sm font-medium">Could not load data</div>
      <div className="max-w-md break-words text-xs text-muted">{msg}</div>
      {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-surface2", className)} />;
}

/** Standard loading / error / empty wrapper for a query result. */
export function QueryBoundary<T>({
  query, children, isEmpty, empty,
}: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
}) {
  if (query.isLoading) return <Loading />;
  if (query.error && query.data === undefined) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data === undefined) return null;
  if (isEmpty?.(query.data)) return <>{empty}</>;
  return <>{children(query.data)}</>;
}

import { cn } from "../../lib/cn";

export interface TabItem<T extends string> { value: T; label: string }

export function Tabs<T extends string>({
  items, value, onChange, className, size = "md",
}: { items: TabItem<T>[]; value: T; onChange: (v: T) => void; className?: string; size?: "sm" | "md" }) {
  return (
    <div role="tablist" className={cn("inline-flex rounded-md border border-line bg-surface2 p-0.5", className)}>
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          type="button"
          aria-selected={it.value === value}
          onClick={() => onChange(it.value)}
          className={cn(
            "rounded px-2.5 font-medium transition-colors",
            size === "sm" ? "py-0.5 text-xs" : "py-1 text-sm",
            it.value === value ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { Search, X } from "lucide-react";
import { cn } from "../../lib/cn";

export function Field({
  label, hint, children, className, htmlFor, error,
}: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string; htmlFor?: string; error?: string | null }) {
  return (
    <div className={className}>
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? <p className="mt-1 text-xs text-err">{error}</p> : hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

/** Free-form chips (tags / domains). Enter or comma adds, Backspace on empty removes the last. */
export function ChipsInput({
  value, onChange, placeholder, label,
}: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; label?: string }) {
  const [draft, setDraft] = useState("");
  const id = useId();
  const add = (raw: string) => {
    const parts = raw.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
  };
  return (
    <div className="input flex min-h-[2rem] flex-wrap items-center gap-1 !py-1">
      {value.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded bg-surface2 px-1.5 py-0.5 text-xs">
          {v}
          <button type="button" aria-label={`Remove ${v}`} className="text-muted hover:text-err" onClick={() => onChange(value.filter((x) => x !== v))}>
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        aria-label={label ?? placeholder ?? "Add item"}
        className="min-w-[8rem] flex-1 bg-transparent text-sm outline-none placeholder:text-muted/70"
        value={draft}
        placeholder={value.length ? "" : placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => add(draft)}
      />
    </div>
  );
}

export interface MultiOption { value: string; label: string; hint?: string }

/** Checkbox list with filter, for tools/skills. */
export function MultiSelect({
  options, value, onChange, emptyText = "No options", maxHeight = "11rem",
}: { options: MultiOption[]; value: string[]; onChange: (v: string[]) => void; emptyText?: string; maxHeight?: string }) {
  const [q, setQ] = useState("");
  const shown = options.filter((o) => (o.label + " " + (o.hint ?? "")).toLowerCase().includes(q.toLowerCase()));
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div className="rounded-md border border-line bg-surface">
      <div className="flex items-center gap-1.5 border-b border-line px-2">
        <Search className="h-3.5 w-3.5 text-muted" aria-hidden />
        <input
          aria-label="Filter options"
          className="h-7 flex-1 bg-transparent text-sm outline-none placeholder:text-muted/70"
          placeholder="Filter…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="text-xs text-muted">{value.length} selected</span>
      </div>
      <div className="overflow-y-auto p-1" style={{ maxHeight }}>
        {shown.length === 0 && <div className="px-2 py-3 text-center text-xs text-muted">{emptyText}</div>}
        {shown.map((o) => (
          <label key={o.value} className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 hover:bg-surface2">
            <input type="checkbox" className="mt-0.5 accent-[rgb(var(--accent))]" checked={value.includes(o.value)} onChange={() => toggle(o.value)} />
            <span className="min-w-0">
              <span className="text-sm">{o.label}</span>
              {o.hint && <span className="block truncate text-xs text-muted">{o.hint}</span>}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

export function Segmented<T extends string>({
  options, value, onChange, label, size = "md",
}: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string; size?: "sm" | "md" }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line bg-surface2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-2 text-xs font-medium transition-colors",
            size === "sm" ? "py-px" : "py-0.5",
            o.value === value ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SearchInput({
  value, onChange, placeholder = "Search…", className,
}: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) {
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" aria-hidden />
      <input
        type="search"
        aria-label={placeholder}
        className="input !pl-7"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

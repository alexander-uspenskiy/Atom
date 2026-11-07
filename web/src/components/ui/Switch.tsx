import { cn } from "../../lib/cn";

export function Switch({
  checked, onChange, label, disabled, id,
}: { checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean; id?: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
        checked ? "border-accent bg-accent" : "border-line bg-surface2",
      )}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 rounded-full shadow transition-transform",
          checked ? "translate-x-[18px] bg-accent-fg" : "translate-x-[3px] bg-muted",
        )}
      />
    </button>
  );
}

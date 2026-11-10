import { Copy, RotateCcw } from "lucide-react";
import { useToast } from "../ui/Toast";
import { fmtFull } from "../../lib/format";
import { cn } from "../../lib/cn";

const btn = "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted hover:bg-surface2 hover:text-fg disabled:opacity-50";

/** Timestamp + Copy + optional re-send button shown under a chat message. */
export function MessageActions({ at, text, onResend, resendLabel = "Run again", resendTitle, disabled, className }: {
  at?: number; text?: string; onResend?: () => void; resendLabel?: string; resendTitle?: string; disabled?: boolean; className?: string;
}) {
  const toast = useToast();
  const copy = () => {
    void navigator.clipboard.writeText(text ?? "").then(() => toast.success("Copied"), () => toast.error("Could not copy"));
  };
  const when = fmtFull(at);
  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)} data-testid="msg-actions">
      {when && <time className="mr-1 text-xs tabular-nums text-muted" dateTime={new Date((at ?? 0) * 1000).toISOString()}>{when}</time>}
      {text ? (
        <button type="button" className={btn} onClick={copy} title="Copy this message" aria-label="Copy message">
          <Copy className="h-3 w-3" aria-hidden /> Copy
        </button>
      ) : null}
      {onResend && (
        <button type="button" className={btn} onClick={onResend} disabled={disabled} title={resendTitle ?? "Send the same prompt again"} aria-label={resendLabel}>
          <RotateCcw className="h-3 w-3" aria-hidden /> {resendLabel}
        </button>
      )}
    </div>
  );
}

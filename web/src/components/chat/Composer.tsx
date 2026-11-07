import { useEffect, useRef, type KeyboardEvent } from "react";
import { Brain, Send, Square } from "lucide-react";
import { Button } from "../ui/Button";
import { Segmented } from "../ui/Fields";
import { Switch } from "../ui/Switch";

export type ChatEffort = "low" | "medium" | "xhigh";
export interface ChatPrefs { thinking: boolean; effort: ChatEffort }

export function Composer({
  value, onChange, onSend, onStop, streaming, prefs, onPrefs, disabled, autoFocusKey,
}: {
  value: string; onChange: (v: string) => void; onSend: () => void; onStop: () => void; streaming: boolean;
  prefs: ChatPrefs; onPrefs: (p: ChatPrefs) => void; disabled?: boolean; autoFocusKey?: string | null;
}) {
  const ta = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);
  useEffect(() => ta.current?.focus(), [autoFocusKey]);
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!streaming && value.trim()) onSend();
    }
  };
  return (
    <div className="border-t border-line bg-surface p-3">
      <div className="rounded-lg border border-line bg-bg focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/25">
        <textarea
          ref={ta}
          aria-label="Message"
          rows={1}
          className="block max-h-[200px] w-full resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted/70"
          placeholder="Ask Atom anything — it can schedule runs, create agents, save memories…  (Enter to send, Shift+Enter for newline)"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="flex flex-wrap items-center gap-3 border-t border-line/70 px-2 py-1.5">
          <label className="inline-flex items-center gap-1.5 text-xs text-muted" title="Thinking on = better reasoning but breaks the prompt cache and is slower">
            <Brain className="h-3.5 w-3.5" aria-hidden />
            Thinking
            <Switch checked={prefs.thinking} onChange={(thinking) => onPrefs({ ...prefs, thinking })} label="Thinking" />
          </label>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            Effort
            <Segmented<ChatEffort>
              label="Effort"
              size="sm"
              value={prefs.effort}
              onChange={(effort) => onPrefs({ ...prefs, effort })}
              options={[{ value: "low", label: "low" }, { value: "medium", label: "medium" }, { value: "xhigh", label: "xhigh" }]}
            />
          </span>
          <div className="ml-auto">
            {streaming ? (
              <Button size="sm" variant="danger" icon={<Square className="h-3.5 w-3.5" />} onClick={onStop}>Stop</Button>
            ) : (
              <Button size="sm" variant="primary" icon={<Send className="h-3.5 w-3.5" />} disabled={!value.trim() || disabled} onClick={onSend}>Send</Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Brain, Send, Square, Wrench } from "lucide-react";
import { useChatTools } from "../../api/hooks";
import { ToolList } from "../ToolList";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { Segmented } from "../ui/Fields";
import { AttachButton, AttachmentStrip, imagesFromClipboard, type AttachmentsApi } from "./Attachments";
import { Switch } from "../ui/Switch";

export type ChatEffort = "low" | "medium" | "xhigh";
export interface ChatPrefs { thinking: boolean; effort: ChatEffort }

export function Composer({
  value, onChange, onSend, onStop, streaming, prefs, onPrefs, disabled, autoFocusKey, attachments,
}: {
  value: string; onChange: (v: string) => void; onSend: () => void; onStop: () => void; streaming: boolean;
  prefs: ChatPrefs; onPrefs: (p: ChatPrefs) => void; disabled?: boolean; autoFocusKey?: string | null;
  attachments: AttachmentsApi;
}) {
  const hasContent = !!value.trim() || attachments.ids.length > 0;
  const canSend = hasContent && !attachments.busy && !disabled;
  const ta = useRef<HTMLTextAreaElement>(null);
  const tools = useChatTools();
  const [toolsOpen, setToolsOpen] = useState(false);
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
      if (!streaming && canSend) onSend();
    }
  };
  return (
    <div className="border-t border-line bg-surface p-3">
      <div className="rounded-lg border border-line bg-bg focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/25" data-testid="composer">
        <AttachmentStrip api={attachments} />
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
          onPaste={(e) => {
            const files = imagesFromClipboard(e);
            if (files.length) {
              e.preventDefault();
              attachments.add(files);
            }
          }}
        />
        <div className="flex flex-wrap items-center gap-3 border-t border-line/70 px-2 py-1.5">
          <AttachButton api={attachments} disabled={disabled} />
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
          <button
            type="button"
            onClick={() => setToolsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface2 hover:text-fg"
            title="Tools available in this session"
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden />
            Tools ({tools.data?.length ?? "…"})
          </button>
          <div className="ml-auto">
            {streaming ? (
              <Button size="sm" variant="danger" icon={<Square className="h-3.5 w-3.5" />} onClick={onStop}>Stop</Button>
            ) : (
              <Button size="sm" variant="primary" icon={<Send className="h-3.5 w-3.5" />} disabled={!canSend} onClick={onSend}>Send</Button>
            )}
          </div>
        </div>
      </div>
      <Dialog open={toolsOpen} onClose={() => setToolsOpen(false)} title={`Tools available in this chat (${tools.data?.length ?? 0})`}>
        <ToolList tools={tools.data ?? []} />
      </Dialog>
    </div>
  );
}

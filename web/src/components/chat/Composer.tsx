import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Brain, FolderOpen, Send, Sparkles, Square, Wrench } from "lucide-react";
import { useChatTools, useSkills, useTools } from "../../api/hooks";
import type { ChatMode, Project } from "../../api/types";
import { SkillList } from "../SkillList";
import { ToolList } from "../ToolList";
import { Dialog } from "../ui/Dialog";
import { FolderPicker } from "../ui/FolderPicker";
import { Button } from "../ui/Button";
import { Segmented } from "../ui/Fields";
import { ContextRing } from "./ContextRing";
import { AttachButton, AttachmentStrip, imagesFromClipboard, type AttachmentsApi } from "./Attachments";
import { Switch } from "../ui/Switch";

export type ChatEffort = "low" | "medium" | "xhigh";
export interface ChatPrefs { thinking: boolean; effort: ChatEffort; workdir?: string; mode?: ChatMode }

export function Composer({
  value, onChange, onSend, onStop, streaming, prefs, onPrefs, disabled, autoFocusKey, attachments, project, convId,
}: {
  value: string; onChange: (v: string) => void; onSend: () => void; onStop: () => void; streaming: boolean;
  prefs: ChatPrefs; onPrefs: (p: ChatPrefs) => void; disabled?: boolean; autoFocusKey?: string | null;
  attachments: AttachmentsApi; project?: Project | null; convId?: string | null;
}) {
  const hasContent = !!value.trim() || attachments.ids.length > 0;
  const canSend = hasContent && !attachments.busy && !disabled;
  const ta = useRef<HTMLTextAreaElement>(null);
  const chatTools = useChatTools();
  const agentTools = useTools();
  const active = (l?: { enabled?: boolean }[]) => (l ?? []).filter((t) => t.enabled !== false).length;
  const total = chatTools.data && agentTools.data ? active(chatTools.data) + active(agentTools.data) : null;
  const [toolsOpen, setToolsOpen] = useState(false);
  const skills = useSkills(project?.id);
  const skillCount = skills.data ? active(skills.data) : null;
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const terminalOn = chatTools.data?.some((t) => t.name === "run_command" && t.enabled !== false) ?? false;
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
          <span className="inline-flex items-center gap-1.5 text-xs text-muted" title="Auto: runs commands on its own. Manual: you approve each command and run. Plan: read-only, only proposes a plan.">
            Mode
            <Segmented<ChatMode>
              label="Mode"
              size="sm"
              value={prefs.mode ?? "auto"}
              onChange={(mode) => onPrefs({ ...prefs, mode })}
              options={[{ value: "auto", label: "Auto" }, { value: "manual", label: "Manual" }, { value: "plan", label: "Plan" }]}
            />
          </span>
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
          {terminalOn && project?.folder && (
            <span className="inline-flex max-w-[16rem] items-center gap-1.5 px-1.5 py-0.5 text-xs text-muted" title={`Project folder: ${project.folder}`}>
              <FolderOpen className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="truncate font-mono">{project.folder.split("/").filter(Boolean).pop() ?? "/"}</span>
            </span>
          )}
          {terminalOn && !project?.folder && (
            <button
              type="button"
              onClick={() => setFolderOpen(true)}
              className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface2 hover:text-fg"
              title="Working folder for terminal commands in this chat"
            >
              <FolderOpen className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="truncate font-mono">{prefs.workdir ? prefs.workdir.split("/").filter(Boolean).pop() ?? "/" : "Default folder"}</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setToolsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface2 hover:text-fg"
            title="All tools available: chat assistant + web agents"
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden />
            Tools ({total ?? "…"})
          </button>
          <button
            type="button"
            onClick={() => setSkillsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface2 hover:text-fg"
            title="Skills available here: yours + this project's"
          >
            <Sparkles className="h-3.5 w-3.5" aria-hidden />
            Skills ({skillCount ?? "…"})
          </button>
          <div className="ml-auto flex items-center gap-3">
            {convId && <ContextRing convId={convId} thinking={prefs.thinking} effort={prefs.effort} />}
            {streaming ? (
              <Button size="sm" variant="danger" icon={<Square className="h-3.5 w-3.5" />} onClick={onStop}>Stop</Button>
            ) : (
              <Button size="sm" variant="primary" icon={<Send className="h-3.5 w-3.5" />} disabled={!canSend} onClick={onSend}>Send</Button>
            )}
          </div>
        </div>
      </div>
      <Dialog open={folderOpen} onClose={() => setFolderOpen(false)} title="Terminal working folder (this chat)">
        <p className="mb-2 text-xs text-muted">Where the assistant's shell commands start. Empty = the folder from Settings → Terminal.</p>
        <FolderPicker value={prefs.workdir ?? ""} onChange={(workdir) => onPrefs({ ...prefs, workdir })} />
      </Dialog>
      <Dialog open={skillsOpen} onClose={() => setSkillsOpen(false)} title={`Skills (${skillCount ?? 0})`}>
        <p className="mb-2 text-xs text-muted">Reusable procedures the assistant and web agents can load on demand. User skills live in ~/.atom/skills; project skills in the project folder's .atom/skills or .agents/skills.</p>
        <SkillList skills={skills.data ?? []} />
      </Dialog>
      <Dialog open={toolsOpen} onClose={() => setToolsOpen(false)} title={`Tools (${total ?? 0})`}>
        <div className="space-y-4">
          <section>
            <h3 className="mb-1.5 text-xs font-semibold">Chat assistant ({active(chatTools.data)})</h3>
            <ToolList tools={chatTools.data ?? []} />
          </section>
          <section>
            <h3 className="mb-1.5 text-xs font-semibold">Web agents ({active(agentTools.data)})</h3>
            <ToolList tools={agentTools.data ?? []} />
          </section>
        </div>
      </Dialog>
    </div>
  );
}

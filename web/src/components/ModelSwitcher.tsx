import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Loader2, Play, Square } from "lucide-react";
import { api } from "../api/client";
import { qk, useModels } from "../api/hooks";
import type { ModelInfo, ModelsPayload } from "../api/types";
import { errMsg } from "../lib/format";
import { cn } from "../lib/cn";
import { useToast } from "./ui/Toast";

const ICON_BTN = "rounded p-1 text-muted hover:bg-surface2 hover:text-fg";

function state(m: ModelInfo): { text: string; dot: string } {
  if (m.running) return { text: "running", dot: "bg-ok" };
  if (m.starting) return { text: "loading…", dot: "bg-warn" };
  if (m.download?.active) return { text: `downloading ${m.download.percent}%`, dot: "bg-warn" };
  if (m.installed) return { text: "stopped", dot: "bg-muted" };
  return { text: `not downloaded · ${m.size_gb} GB`, dot: "bg-muted" };
}

/** Wraps the sidebar model name: click to list the available models, switch the active one, start/stop/download. */
export function ModelSwitcher({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const models = useModels(open ? 2000 : false);   // poll while open: download progress, server loading
  const done = (p: ModelsPayload) => { qc.setQueryData(qk.models, p); void qc.invalidateQueries({ queryKey: qk.status }); };
  const activate = useMutation({ mutationFn: (id: string) => api.activateModel(id), onSuccess: done, onError: (e) => toast.error(errMsg(e)) });
  const act = useMutation({
    mutationFn: ({ id, a }: { id: string; a: "start" | "stop" | "download" }) => api.modelAction(id, a),
    onSuccess: done, onError: (e) => toast.error(errMsg(e)),
  });

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button type="button" className="w-full rounded text-left hover:bg-surface2" title="Switch model"
        aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {children}
      </button>
      {open && (
        <div role="dialog" aria-label="Models" className="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-lg border border-line bg-surface p-1 shadow-lg">
          <div className="px-2 py-1.5 text-xs font-medium text-muted">Models · click one to use it</div>
          {(models.data?.models ?? []).map((m) => {
            const st = state(m);
            const busy = (activate.isPending && activate.variables === m.id) || (act.isPending && act.variables?.id === m.id);
            return (
              <div key={m.id} className={cn("flex items-start gap-2 rounded px-2 py-2", m.active && "bg-surface2")}>
                <button type="button" className="flex min-w-0 flex-1 items-start gap-2 text-left" disabled={busy || (!m.installed && !m.running)}
                  onClick={() => { if (!m.active) activate.mutate(m.id); }}>
                  <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", st.dot)} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 text-sm font-medium">{m.label}{m.active && <Check className="h-3.5 w-3.5 text-ok" aria-label="active" />}</span>
                    <span className="block text-[11px] text-muted">{m.detail}</span>
                    <span className="block text-[11px] text-muted">{st.text}</span>
                    {m.download && (
                      <span className="mt-1 block h-1.5 w-full overflow-hidden rounded bg-line" role="progressbar" aria-valuenow={m.download.percent}>
                        <span className="block h-full bg-accent" style={{ width: `${m.download.percent}%` }} />
                      </span>
                    )}
                  </span>
                </button>
                <span className="flex shrink-0 items-center">
                  {busy || m.starting ? <Loader2 className="h-4 w-4 animate-spin text-muted" aria-label="working" /> :
                    !m.installed && !m.download?.active ? (
                      <button type="button" className={ICON_BTN} title="Download" aria-label={`Download ${m.label}`} onClick={() => act.mutate({ id: m.id, a: "download" })}><Download className="h-4 w-4" /></button>
                    ) : m.installed && !m.running ? (
                      <button type="button" className={ICON_BTN} title="Start server" aria-label={`Start ${m.label}`} onClick={() => act.mutate({ id: m.id, a: "start" })}><Play className="h-4 w-4" /></button>
                    ) : m.running && m.managed ? (
                      <button type="button" className={ICON_BTN} title="Stop server (free memory)" aria-label={`Stop ${m.label}`} onClick={() => act.mutate({ id: m.id, a: "stop" })}><Square className="h-4 w-4" /></button>
                    ) : null}
                </span>
              </div>
            );
          })}
          <p className="px-2 py-1.5 text-[11px] text-muted">Each agent can also pick its own model (Agents → edit). Two 27B models together need about 40 GB of memory.</p>
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { qk, useVariables } from "../api/hooks";
import type { Variable } from "../api/types";
import { Badge } from "./ui/Badge";
import { Button, IconButton } from "./ui/Button";
import { Card, CardHeader } from "./ui/Card";
import { ConfirmDialog, Dialog } from "./ui/Dialog";
import { Field } from "./ui/Fields";
import { ErrorState, Loading } from "./ui/Spinner";
import { Switch } from "./ui/Switch";
import { useToast } from "./ui/Toast";
import { errMsg } from "../lib/format";

interface Draft { name: string; value: string; secret: boolean; description: string; domains: string }
const blank: Draft = { name: "", value: "", secret: false, description: "", domains: "" };
const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

function VariableDialog({ initial, existing, onClose }: { initial: Variable | null; existing: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!initial;
  const [d, setD] = useState<Draft>(
    initial ? { name: initial.name, value: initial.value ?? "", secret: initial.secret, description: initial.description, domains: initial.domains.join(", ") } : blank,
  );
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const nameErr = editing || !d.name ? null : !NAME_RE.test(d.name) ? "Letters, digits and _ only; must not start with a digit" : existing.includes(d.name) ? "Already exists" : null;
  const keepSecret = editing && initial.secret && d.secret && d.value === "";   // blank = keep the stored secret
  const valid = !!d.name && !nameErr && (keepSecret || d.value !== "");
  const save = useMutation({
    mutationFn: () =>
      api.variableSave(d.name, {
        value: keepSecret ? undefined : d.value,
        secret: d.secret,
        description: d.description,
        domains: d.domains.split(/[,\s]+/).filter(Boolean),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.variables });
      toast.success(`Saved ${d.name}`);
      onClose();
    },
    onError: (e) => toast.error(`Could not save: ${errMsg(e)}`),
  });
  return (
    <Dialog
      open onClose={onClose} title={editing ? `Edit ${d.name}` : "Add variable"}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </>}
    >
      <div className="space-y-3">
        <Field label="Name" htmlFor="var-name" error={nameErr} hint={<>Agents write <span className="font-mono">{`{{${d.name || "NAME"}}}`}</span> in a tool argument and the value is filled in when the tool runs.</>}>
          <input id="var-name" className="input w-full font-mono" value={d.name} disabled={editing} onChange={(e) => set("name", e.target.value)} placeholder="GITHUB_TOKEN" spellCheck={false} autoComplete="off" />
        </Field>
        <Switch id="var-secret" checked={d.secret} onChange={(v) => set("secret", v)} label="Secret (hidden from the agent and the UI)" />
        <Field label="Value" htmlFor="var-value" hint={d.secret ? (editing && initial.secret ? "Leave blank to keep the current value." : "Stored in plain text in the local database; never shown again.") : "Visible to the agent in its prompt."}>
          <input id="var-value" className="input w-full font-mono" type={d.secret ? "password" : "text"} value={d.value} onChange={(e) => set("value", e.target.value)} placeholder={keepSecret || (editing && initial.secret) ? "•••••••• (unchanged)" : ""} spellCheck={false} autoComplete="new-password" />
        </Field>
        <Field label="Description" htmlFor="var-desc" hint="Shown to the agent so it knows what the value is for.">
          <input id="var-desc" className="input w-full" value={d.description} onChange={(e) => set("description", e.target.value)} placeholder="Login password for the staging site" />
        </Field>
        {d.secret && (
          <Field label="Allowed domains" htmlFor="var-dom" hint="Optional, comma-separated. The secret is only filled in while the browser is on one of these sites (subdomains included); leave empty to allow any site.">
            <input id="var-dom" className="input w-full font-mono" value={d.domains} onChange={(e) => set("domains", e.target.value)} placeholder="example.com, app.example.org" spellCheck={false} />
          </Field>
        )}
      </div>
    </Dialog>
  );
}

export function Variables() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useVariables();
  const [dialog, setDialog] = useState<Variable | null | undefined>(undefined); // undefined = closed, null = new
  const [del, setDel] = useState<Variable | null>(null);
  const remove = useMutation({
    mutationFn: (n: string) => api.variableDelete(n),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: qk.variables }); setDel(null); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const vars = q.data ?? [];
  return (
    <Card>
      <CardHeader
        title="Environment & secrets" icon={<KeyRound className="h-3.5 w-3.5" />}
        actions={<Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setDialog(null)}>Add variable</Button>}
      />
      {q.isLoading && <Loading />}
      {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <p className="px-3 pt-2 text-xs text-muted">
          Agents use these by writing <span className="font-mono">{"{{NAME}}"}</span> in tool arguments (for example in <span className="font-mono">type</span> or <span className="font-mono">open_url</span>).
          Secret values are never shown to the model and are scrubbed from run logs; they can only be used with typing, selecting, opening URLs and MCP tools. Changes apply to the next run.
        </p>
      )}
      {q.data && vars.length === 0 && <p className="px-3 py-4 text-sm text-muted">No variables yet.</p>}
      <div className="divide-y divide-line">
        {vars.map((v) => (
          <div key={v.name} className="flex items-start gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-medium">{v.name}</span>
                {v.secret ? <Badge tone="warn"><Lock className="mr-1 inline h-3 w-3" aria-hidden />secret</Badge> : <Badge tone="neutral">env</Badge>}
                {v.secret && v.domains.length > 0 && <Badge tone="info">{v.domains.join(", ")}</Badge>}
              </div>
              <div className="truncate font-mono text-[11px] text-muted">{v.secret ? "••••••••" : v.value}</div>
              {v.description && <p className="mt-0.5 text-xs text-muted">{v.description}</p>}
            </div>
            <IconButton label={`Edit ${v.name}`} onClick={() => setDialog(v)}><Pencil className="h-3.5 w-3.5" /></IconButton>
            <IconButton label={`Delete ${v.name}`} onClick={() => setDel(v)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
          </div>
        ))}
      </div>
      {dialog !== undefined && <VariableDialog initial={dialog} existing={vars.map((v) => v.name)} onClose={() => setDialog(undefined)} />}
      <ConfirmDialog open={del !== null} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.name)} loading={remove.isPending} title="Delete variable?" confirmLabel="Delete" message={<>“{del?.name}” will be removed. Agents that reference it will see the placeholder unfilled.</>} />
    </Card>
  );
}

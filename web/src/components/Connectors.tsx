import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, LogIn, LogOut, Pencil, Plus, Trash2, Unplug, Zap } from "lucide-react";
import { api } from "../api/client";
import { qk, useConnectors } from "../api/hooks";
import type { ConnectorField, ConnectorItem, ConnectorsPayload, ConnectorType } from "../api/types";
import { Badge, type Tone } from "./ui/Badge";
import { Button, IconButton } from "./ui/Button";
import { Card, CardHeader } from "./ui/Card";
import { ConfirmDialog, Dialog } from "./ui/Dialog";
import { Field } from "./ui/Fields";
import { Select } from "./ui/Select";
import { ErrorState, Loading } from "./ui/Spinner";
import { Switch } from "./ui/Switch";
import { useToast } from "./ui/Toast";
import { errMsg } from "../lib/format";

const tone: Record<string, Tone> = { ready: "ok", error: "err", disabled: "neutral", pending: "warn", needs_auth: "warn" };
type Vals = Record<string, unknown>;

// The form is generated from the connector type's field schema (served by the backend), so new connector types
// need no UI changes.
function FieldInput({ f, value, hasSecret, onChange }: { f: ConnectorField; value: unknown; hasSecret: boolean; onChange: (v: unknown) => void }) {
  const id = `conn-${f.key}`;
  if (f.type === "boolean")
    return (
      <div>
        <label htmlFor={id} className="flex cursor-pointer items-center gap-2 text-sm">
          <Switch id={id} checked={value === true} onChange={onChange} label={f.label} /> {f.label}
        </label>
        {f.help && <p className="mt-1 text-xs text-muted">{f.help}</p>}
      </div>
    );
  return (
    <Field label={f.label} htmlFor={id} hint={f.help}>
      <input
        id={id} className="input w-full font-mono" spellCheck={false} autoComplete={f.type === "password" ? "new-password" : "off"}
        type={f.type === "password" ? "password" : f.type === "number" ? "number" : "text"}
        value={String(value ?? "")} onChange={(e) => onChange(f.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value)}
        placeholder={f.type === "password" && hasSecret ? "•••••••• (unchanged)" : f.placeholder}
      />
    </Field>
  );
}

function ConnectorDialog({ types, initial, existing, onClose }: { types: ConnectorType[]; initial: ConnectorItem | null; existing: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!initial;
  const [type, setType] = useState(initial?.type ?? types[0]?.type ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [vals, setVals] = useState<Vals>(initial?.config ?? {});
  const spec = types.find((t) => t.type === type);
  const nameErr = editing || !name ? null : !/^[A-Za-z0-9_-]{1,30}$/.test(name) ? "Letters, digits, - and _ only" : existing.includes(name) ? "Already exists" : null;
  const missing = (spec?.fields ?? []).some((f) => f.required && f.type !== "boolean" && !vals[f.key] && !(f.type === "password" && initial?.has_secret[f.key]));
  const save = useMutation({
    mutationFn: () => api.connectorSave(name, { type, enabled, config: vals }),
    onSuccess: (res: ConnectorsPayload) => {
      qc.setQueryData(qk.connectors, res);
      void qc.invalidateQueries({ queryKey: qk.tools });
      const it = res.items.find((x) => x.name === name);
      if (it?.state === "error") toast.error(`Saved, but ${name} is not ready: ${it.error}`);
      else toast.success(`Saved ${name}`);
      onClose();
    },
    onError: (e) => toast.error(`Could not save: ${errMsg(e)}`),
  });
  return (
    <Dialog
      open onClose={onClose} title={editing ? `Edit ${name}` : "Add connector"}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!name || !!nameErr || missing} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </>}
    >
      <div className="space-y-3">
        {!editing && (
          <Field label="Type" htmlFor="conn-type" hint={spec?.description}>
            <Select id="conn-type" className="w-full" value={type} onChange={(e) => { setType(e.target.value); setVals({}); }} options={types.map((t) => ({ value: t.type, label: t.label }))} />
          </Field>
        )}
        <Field label="Name" htmlFor="conn-name" error={nameErr} hint="Used in tool names, e.g. gmail_<name>_search. Lets you connect several accounts.">
          <input id="conn-name" className="input w-full" value={name} disabled={editing} onChange={(e) => setName(e.target.value)} placeholder="work" spellCheck={false} />
        </Field>
        {spec?.fields.map((f) => (
          <FieldInput key={f.key} f={f} value={vals[f.key] ?? (f.type === "boolean" ? f.default : "")} hasSecret={!!initial?.has_secret[f.key]} onChange={(v) => setVals((x) => ({ ...x, [f.key]: v }))} />
        ))}
        <label htmlFor="conn-enabled" className="flex cursor-pointer items-center gap-2 text-sm">
          <Switch id="conn-enabled" checked={enabled} onChange={setEnabled} label="Enabled" /> Enabled
        </label>
      </div>
    </Dialog>
  );
}

export function Connectors() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useConnectors();
  const [dialog, setDialog] = useState<ConnectorItem | null | undefined>(undefined); // undefined = closed, null = new
  const [del, setDel] = useState<ConnectorItem | null>(null);
  const done = (res: ConnectorsPayload) => {
    qc.setQueryData(qk.connectors, res);
    void qc.invalidateQueries({ queryKey: qk.tools });
  };
  const remove = useMutation({ mutationFn: (n: string) => api.connectorDelete(n), onSuccess: (r) => { done(r); setDel(null); }, onError: (e) => toast.error(errMsg(e)) });
  const toggle = useMutation({
    mutationFn: (c: ConnectorItem) => api.connectorSave(c.name, { type: c.type, enabled: !c.enabled, config: c.config }),
    onSuccess: done, onError: (e) => toast.error(errMsg(e)),
  });
  const test = useMutation({
    mutationFn: (n: string) => api.connectorTest(n),
    onSuccess: (r, n) => (r.ok ? toast.success(`${n}: ${r.message}`) : toast.error(`${n}: ${r.message}`)),
    onError: (e) => toast.error(errMsg(e)),
  });
  const signIn = useMutation({
    mutationFn: (n: string) => api.connectorOAuthStart(n),
    onSuccess: ({ auth_url }) => {
      window.open(auth_url, "_blank", "noopener");
      toast.success("Finish signing in in the new tab; this page updates automatically.");
      const t = window.setInterval(() => void q.refetch().then(() => qc.invalidateQueries({ queryKey: qk.tools })), 2000);
      window.setTimeout(() => window.clearInterval(t), 120000);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const signOut = useMutation({ mutationFn: (n: string) => api.connectorSignOut(n), onSuccess: done, onError: (e) => toast.error(errMsg(e)) });
  const items = q.data?.items ?? [];
  const types = q.data?.types ?? [];
  const label = (t: string) => types.find((x) => x.type === t)?.label ?? t;
  return (
    <Card>
      <CardHeader
        title="Connectors" icon={<Unplug className="h-3.5 w-3.5" />}
        actions={<Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} disabled={!types.length} onClick={() => setDialog(null)}>Add connector</Button>}
      />
      {q.isLoading && <Loading />}
      {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && items.length === 0 && (
        <p className="px-3 py-4 text-sm text-muted">No connectors yet. Available: {types.map((t) => t.label).join(", ")}. Each adds tools agents can use (for example reading and sending Gmail).</p>
      )}
      <div className="divide-y divide-line">
        {items.map((c) => (
          <div key={c.name} className="flex items-start gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{c.name}</span>
                <Badge tone="neutral">{label(c.type)}</Badge>
                <Badge tone={tone[c.state] ?? "neutral"} dot>{c.state === "ready" ? `ready · ${c.tool_names.length} tools` : c.state === "needs_auth" ? "sign-in required" : c.state}</Badge>
              </div>
              {typeof c.config.email === "string" && <div className="truncate font-mono text-[11px] text-muted">{c.config.email}</div>}
              {c.error && <p className="mt-1 text-xs text-err">{c.error}</p>}
              {c.tool_names.length > 0 && <p className="mt-1 line-clamp-2 text-xs text-muted">{c.tool_names.join(", ")}</p>}
            </div>
            {types.find((t) => t.type === c.type)?.oauth && (c.signed_in
              ? <Button size="sm" icon={<LogOut className="h-3.5 w-3.5" />} loading={signOut.isPending && signOut.variables === c.name} onClick={() => signOut.mutate(c.name)}>Sign out</Button>
              : <Button size="sm" variant="primary" icon={<LogIn className="h-3.5 w-3.5" />} loading={signIn.isPending && signIn.variables === c.name} onClick={() => signIn.mutate(c.name)}>Sign in</Button>)}
            <Switch id={`conn-on-${c.name}`} checked={c.enabled} onChange={() => toggle.mutate(c)} label={`Enable ${c.name}`} />
            <IconButton label={`Test ${c.name}`} onClick={() => test.mutate(c.name)}>{test.isPending && test.variables === c.name ? <Zap className="h-3.5 w-3.5 animate-pulse" /> : <CheckCircle2 className="h-3.5 w-3.5" />}</IconButton>
            <IconButton label={`Edit ${c.name}`} onClick={() => setDialog(c)}><Pencil className="h-3.5 w-3.5" /></IconButton>
            <IconButton label={`Delete ${c.name}`} onClick={() => setDel(c)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
          </div>
        ))}
      </div>
      {dialog !== undefined && <ConnectorDialog types={types} initial={dialog} existing={items.map((i) => i.name)} onClose={() => setDialog(undefined)} />}
      <ConfirmDialog open={del !== null} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.name)} loading={remove.isPending} title="Remove connector?" confirmLabel="Remove" message={<>“{del?.name}” and its saved credentials will be deleted. Agents that selected its tools will lose them.</>} />
    </Card>
  );
}

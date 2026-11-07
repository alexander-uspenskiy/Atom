import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plug, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { qk, useMcp } from "../api/hooks";
import type { McpServer, McpServerConfig, McpStatus } from "../api/types";
import { Badge, type Tone } from "./ui/Badge";
import { Button, IconButton } from "./ui/Button";
import { Card, CardHeader } from "./ui/Card";
import { ConfirmDialog, Dialog } from "./ui/Dialog";
import { Field, Segmented } from "./ui/Fields";
import { ErrorState, Loading } from "./ui/Spinner";
import { Switch } from "./ui/Switch";
import { useToast } from "./ui/Toast";
import { errMsg } from "../lib/format";

const tone: Record<string, Tone> = { connected: "ok", error: "err", disabled: "neutral", pending: "warn" };

const toLines = (o?: Record<string, string>) => Object.entries(o ?? {}).map(([k, v]) => `${k}=${v}`).join("\n");
function fromLines(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf(line.includes("=") ? "=" : ":");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

interface Draft { name: string; kind: "local" | "remote"; command: string; args: string; env: string; url: string; headers: string; disabled: boolean }
const blank: Draft = { name: "", kind: "local", command: "", args: "", env: "", url: "", headers: "", disabled: false };

function toDraft(s: McpServer): Draft {
  const c = s.config;
  return {
    name: s.name, kind: c.url ? "remote" : "local", command: c.command ?? "", args: (c.args ?? []).join("\n"),
    env: toLines(c.env), url: c.url ?? "", headers: toLines(c.headers).replace(/=/, ": "), disabled: !!c.disabled,
  };
}

function toConfig(d: Draft): McpServerConfig {
  const base = d.disabled ? { disabled: true } : {};
  if (d.kind === "remote") {
    const headers = Object.fromEntries(d.headers.split("\n").map((l) => l.split(/:(.*)/s)).filter((p) => p[0]?.trim() && p[1] !== undefined).map((p) => [p[0].trim(), p[1].trim()]));
    return { ...base, url: d.url.trim(), headers };
  }
  return { ...base, command: d.command.trim(), args: d.args.split("\n").map((a) => a.trim()).filter(Boolean), env: fromLines(d.env) };
}

function ServerDialog({ initial, existing, onClose }: { initial: Draft | null; existing: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [d, setD] = useState<Draft>(initial ?? blank);
  const editing = !!initial?.name;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const nameErr: string | null = editing || !d.name ? null : !/^[A-Za-z0-9_-]{1,40}$/.test(d.name) ? "Letters, digits, - and _ only" : existing.includes(d.name) ? "Already exists" : null;
  const valid = !!d.name && !nameErr && (d.kind === "local" ? !!d.command.trim() : !!d.url.trim());
  const save = useMutation({
    mutationFn: () => api.mcpSave(d.name, toConfig(d)),
    onSuccess: (res: McpStatus) => {
      qc.setQueryData(qk.mcp, res);
      void qc.invalidateQueries({ queryKey: qk.tools });
      const s = res.servers.find((x) => x.name === d.name);
      if (s?.state === "error") toast.error(`Saved, but ${d.name} failed to connect: ${s.error}`);
      else toast.success(`${d.name}: ${s?.state === "connected" ? `connected, ${s.tools} tools` : s?.state ?? "saved"}`);
      onClose();
    },
    onError: (e) => toast.error(`Could not save: ${errMsg(e)}`),
  });
  return (
    <Dialog
      open onClose={onClose} wide title={editing ? `Edit ${d.name}` : "Add MCP server"}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>{editing ? "Save & reconnect" : "Add & connect"}</Button>
      </>}
    >
      <div className="space-y-3">
        <Field label="Name" htmlFor="mcp-name" error={nameErr} hint="Tools are exposed as mcp_<name>_<tool>.">
          <input id="mcp-name" className="input w-full" value={d.name} disabled={editing} onChange={(e) => set("name", e.target.value)} placeholder="filesystem" spellCheck={false} />
        </Field>
        <Segmented label="Connection type" value={d.kind} onChange={(v) => set("kind", v)} options={[{ value: "local", label: "Local command" }, { value: "remote", label: "Remote URL" }]} />
        {d.kind === "local" ? (
          <>
            <Field label="Command" htmlFor="mcp-cmd"><input id="mcp-cmd" className="input w-full font-mono" value={d.command} onChange={(e) => set("command", e.target.value)} placeholder="npx" spellCheck={false} /></Field>
            <Field label="Arguments" htmlFor="mcp-args" hint="One per line."><textarea id="mcp-args" rows={3} className="input w-full font-mono" value={d.args} onChange={(e) => set("args", e.target.value)} placeholder={"-y\n@modelcontextprotocol/server-filesystem\n/Users/me/docs"} spellCheck={false} /></Field>
            <Field label="Environment" htmlFor="mcp-env" hint="KEY=value, one per line. Stored in plain text in data/mcp.json."><textarea id="mcp-env" rows={2} className="input w-full font-mono" value={d.env} onChange={(e) => set("env", e.target.value)} spellCheck={false} /></Field>
          </>
        ) : (
          <>
            <Field label="URL" htmlFor="mcp-url" hint="Streamable HTTP endpoint."><input id="mcp-url" className="input w-full font-mono" value={d.url} onChange={(e) => set("url", e.target.value)} placeholder="https://example.com/mcp" spellCheck={false} /></Field>
            <Field label="Headers" htmlFor="mcp-hdr" hint="Name: value, one per line (e.g. Authorization). Stored in plain text."><textarea id="mcp-hdr" rows={2} className="input w-full font-mono" value={d.headers} onChange={(e) => set("headers", e.target.value)} spellCheck={false} /></Field>
          </>
        )}
        <Switch id="mcp-disabled" checked={!d.disabled} onChange={(v) => set("disabled", !v)} label="Enabled" />
      </div>
    </Dialog>
  );
}

export function McpServers() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useMcp();
  const [dialog, setDialog] = useState<Draft | null | undefined>(undefined); // undefined = closed, null = new
  const [del, setDel] = useState<McpServer | null>(null);
  const done = (res: McpStatus) => {
    qc.setQueryData(qk.mcp, res);
    void qc.invalidateQueries({ queryKey: qk.tools });
  };
  const reload = useMutation({ mutationFn: api.mcpReload, onSuccess: (r) => { done(r); toast.success("Reconnected all servers"); }, onError: (e) => toast.error(errMsg(e)) });
  const remove = useMutation({ mutationFn: (n: string) => api.mcpDelete(n), onSuccess: (r) => { done(r); setDel(null); }, onError: (e) => toast.error(errMsg(e)) });
  const toggle = useMutation({
    mutationFn: (s: McpServer) => api.mcpSave(s.name, { ...s.config, disabled: !s.config.disabled || undefined }),
    onSuccess: done, onError: (e) => toast.error(errMsg(e)),
  });
  const servers = q.data?.servers ?? [];
  return (
    <Card>
      <CardHeader
        title="MCP servers" icon={<Plug className="h-3.5 w-3.5" />}
        actions={<>
          <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={reload.isPending} onClick={() => reload.mutate()}>Reconnect all</Button>
          <Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setDialog(null)}>Add server</Button>
        </>}
      />
      {q.isLoading && <Loading />}
      {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && servers.length === 0 && <p className="px-3 py-4 text-sm text-muted">No servers yet. Add one to give agents extra tools (files, GitHub, databases…). Saved to <span className="font-mono">{q.data.config_path}</span>.</p>}
      <div className="divide-y divide-line">
        {servers.map((s) => (
          <div key={s.name} className="flex items-start gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{s.name}</span>
                <Badge tone={tone[s.state] ?? "neutral"} dot>{s.state === "connected" ? `connected · ${s.tools} tool${s.tools === 1 ? "" : "s"}` : s.state}</Badge>
              </div>
              <div className="truncate font-mono text-[11px] text-muted">{s.config.url ?? [s.config.command, ...(s.config.args ?? [])].join(" ")}</div>
              {s.error && <p className="mt-1 text-xs text-err">{s.error}</p>}
              {s.tool_names.length > 0 && <p className="mt-1 line-clamp-2 text-xs text-muted">{s.tool_names.join(", ")}</p>}
            </div>
            <Switch id={`mcp-on-${s.name}`} checked={!s.config.disabled} onChange={() => toggle.mutate(s)} label={`Enable ${s.name}`} />
            <IconButton label={`Edit ${s.name}`} onClick={() => setDialog(toDraft(s))}><Pencil className="h-3.5 w-3.5" /></IconButton>
            <IconButton label={`Delete ${s.name}`} onClick={() => setDel(s)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
          </div>
        ))}
      </div>
      {dialog !== undefined && <ServerDialog initial={dialog} existing={servers.map((s) => s.name)} onClose={() => setDialog(undefined)} />}
      <ConfirmDialog open={del !== null} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.name)} loading={remove.isPending} title="Remove MCP server?" confirmLabel="Remove" message={<>“{del?.name}” will be disconnected and removed from the config. Agents that selected its tools will lose them.</>} />
    </Card>
  );
}

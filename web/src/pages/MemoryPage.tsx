import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Brain, Pencil, Pin, PinOff, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { invalidate, useAgents, useMemories } from "../api/hooks";
import type { Memory, MemoryInput } from "../api/types";
import { Page } from "../components/Page";
import { Badge } from "../components/ui/Badge";
import { Button, IconButton } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog, Dialog } from "../components/ui/Dialog";
import { ChipsInput, Field, SearchInput } from "../components/ui/Fields";
import { Select } from "../components/ui/Select";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { errMsg, fmtRelative, truncate } from "../lib/format";

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

function MemoryDialog({ open, onClose, memory }: { open: boolean; onClose: () => void; memory: Memory | null }) {
  const qc = useQueryClient();
  const toast = useToast();
  const agents = useAgents();
  const [f, setF] = useState<MemoryInput>({ title: "", content: "", tags: [], scope: "global", pinned: false });
  useEffect(() => {
    if (open) setF(memory ? { title: memory.title, content: memory.content, tags: memory.tags ?? [], scope: memory.scope, pinned: !!memory.pinned } : { title: "", content: "", tags: [], scope: "global", pinned: false });
  }, [open, memory]);
  const save = useMutation({
    mutationFn: () => (memory ? api.updateMemory(memory.id, f) : api.createMemory(f)),
    onSuccess: () => {
      invalidate(qc, "memories");
      toast.success(memory ? "Memory updated" : "Memory created");
      onClose();
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const scopes = [{ value: "global", label: "global" }, ...(agents.data ?? []).map((a) => ({ value: `agent:${a.id}`, label: `agent: ${a.name}` }))];
  if (!scopes.some((s) => s.value === f.scope)) scopes.push({ value: f.scope, label: f.scope });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={memory ? "Edit memory" : "New memory"}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} disabled={!f.title.trim() || !f.content.trim()} onClick={() => save.mutate()}>Save</Button></>}
    >
      <div className="space-y-3">
        <Field label="Title" htmlFor="mem-title"><input id="mem-title" className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Content" htmlFor="mem-content"><textarea id="mem-content" className="input h-32 resize-y" value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} /></Field>
        <Field label="Tags"><ChipsInput value={f.tags ?? []} onChange={(tags) => setF({ ...f, tags })} placeholder="preferences" label="Tags" /></Field>
        <Field label="Scope" htmlFor="mem-scope"><Select id="mem-scope" value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })} options={scopes} /></Field>
        <label className="flex items-center gap-2 text-sm"><Switch checked={!!f.pinned} onChange={(pinned) => setF({ ...f, pinned })} label="Pinned" /> Pinned (always injected into prompts)</label>
      </div>
    </Dialog>
  );
}

export default function MemoryPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const agents = useAgents();
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("");
  const [pinned, setPinned] = useState("");
  const [status, setStatus] = useState("");
  const dq = useDebounced(q, 300);
  const mem = useMemories({ q: dq, scope, pinned: pinned === "pinned" ? true : undefined, status });
  const [editing, setEditing] = useState<Memory | null>(null);
  const [creating, setCreating] = useState(false);
  const [del, setDel] = useState<Memory | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteMemory(id),
    onSuccess: () => {
      invalidate(qc, "memories");
      toast.success("Memory deleted");
      setDel(null);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const pin = useMutation({
    mutationFn: (m: Memory) => api.updateMemory(m.id, { pinned: !m.pinned }),
    onSuccess: () => invalidate(qc, "memories"),
    onError: (e) => toast.error(errMsg(e)),
  });
  const agentName = (scopeStr: string) => {
    if (!scopeStr.startsWith("agent:")) return scopeStr;
    const id = scopeStr.slice(6);
    return `agent: ${agents.data?.find((a) => a.id === id)?.name ?? id}`;
  };

  return (
    <Page
      title="Memory"
      subtitle="Facts the assistant and agents can recall"
      actions={
        <>
          <SearchInput className="w-56" value={q} onChange={setQ} placeholder="Search memories…" />
          <Select aria-label="Scope" className="w-40" value={scope} onChange={(e) => setScope(e.target.value)} options={[{ value: "", label: "All scopes" }, { value: "global", label: "global" }, ...(agents.data ?? []).map((a) => ({ value: `agent:${a.id}`, label: `agent: ${a.name}` }))]} />
          <Select aria-label="Pinned" className="w-28" value={pinned} onChange={(e) => setPinned(e.target.value)} options={[{ value: "", label: "Any pin" }, { value: "pinned", label: "Pinned" }]} />
          <Select aria-label="Status" className="w-28" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any status" }, { value: "active", label: "Active" }, { value: "pending", label: "Pending" }]} />
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New memory</Button>
        </>
      }
    >
      {mem.isLoading && <Loading />}
      {mem.error && !mem.data && <ErrorState error={mem.error} onRetry={() => void mem.refetch()} />}
      {mem.data && mem.data.length === 0 && (
        <Card><EmptyState icon={Brain} title="No memories found" hint={q || scope || pinned || status ? "Try clearing the filters." : "Add one manually, or let the assistant propose memories in chat."} /></Card>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        {mem.data?.map((m) => (
          <Card key={m.id} className={m.status === "pending" ? "border-warn/50" : undefined}>
            <div className="space-y-1.5 px-3 py-2.5">
              <div className="flex items-start gap-2">
                <h2 className="min-w-0 flex-1 text-sm font-semibold">{m.pinned && <Pin className="mr-1 inline h-3 w-3 text-accent" aria-label="pinned" />}{m.title}</h2>
                <div className="flex shrink-0">
                  <IconButton label={m.pinned ? "Unpin" : "Pin"} onClick={() => pin.mutate(m)}>{m.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}</IconButton>
                  <IconButton label="Edit" onClick={() => setEditing(m)}><Pencil className="h-3.5 w-3.5" /></IconButton>
                  <IconButton label="Delete" className="hover:text-err" onClick={() => setDel(m)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                </div>
              </div>
              <p className="whitespace-pre-wrap break-words text-sm text-muted">{truncate(m.content, 400)}</p>
              {m.status === "pending" && (
                <p className="text-xs text-warn">
                  Proposed by the assistant, awaiting approval. <Link to="/approvals" className="font-medium underline">Review in Approvals →</Link>
                </p>
              )}
              <div className="flex flex-wrap items-center gap-1">
                <Badge tone={m.scope === "global" ? "info" : "neutral"}>{agentName(m.scope)}</Badge>
                {m.status === "pending" && <Badge tone="warn">pending</Badge>}
                {(m.tags ?? []).map((t) => <Badge key={t}>#{t}</Badge>)}
                <span className="ml-auto text-xs text-muted">{m.source ?? "user"} · used {m.use_count ?? 0}× · {m.last_used_at ? `last ${fmtRelative(m.last_used_at)}` : "never used"}</span>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <MemoryDialog open={creating || editing !== null} memory={editing} onClose={() => { setCreating(false); setEditing(null); }} />
      <ConfirmDialog open={del !== null} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.id)} loading={remove.isPending} title="Delete memory?" message={<>“{del?.title}” will be permanently removed.</>} />
    </Page>
  );
}

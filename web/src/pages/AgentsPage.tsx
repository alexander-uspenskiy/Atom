import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { invalidate, useAgents } from "../api/hooks";
import type { Agent } from "../api/types";
import { AgentForm } from "../components/AgentForm";
import { Page } from "../components/Page";
import { RunNowDialog } from "../components/RunNowDialog";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { useToast } from "../components/ui/Toast";
import { errMsg, truncate } from "../lib/format";

export default function AgentsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useAgents();
  const [editing, setEditing] = useState<Agent | null>(null);
  const [creating, setCreating] = useState(false);
  const [running, setRunning] = useState<Agent | null>(null);
  const [del, setDel] = useState<Agent | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteAgent(id),
    onSuccess: () => {
      invalidate(qc, "agents");
      toast.success("Agent deleted");
      setDel(null);
    },
    onError: (e) => {
      toast.error(errMsg(e));
      setDel(null);
    },
  });

  return (
    <Page
      title="Agents"
      subtitle="Saved configurations of the web agent"
      actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New agent</Button>}
    >
      {q.isLoading && <Loading />}
      {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && (
        <Card><EmptyState icon={Bot} title="No agents yet" hint="Create an agent to define tools, skills, domains and model settings for web tasks." action={<Button variant="primary" onClick={() => setCreating(true)}>New agent</Button>} /></Card>
      )}
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {q.data?.map((a) => (
          <Card key={a.id} className="flex flex-col">
            <div className="flex-1 space-y-2 px-3 py-2.5">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent"><Bot className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <h2 className="truncate text-sm font-semibold">{a.name}</h2>
                    {a.is_default && <Badge tone="accent">default</Badge>}
                  </div>
                  <p className="line-clamp-2 text-xs text-muted">{a.description || "No description"}</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-1">
                <Badge>{a.tools == null ? "all tools" : `${a.tools.length} tools`}</Badge>
                <Badge>{(a.skills ?? []).length} skills</Badge>
                <Badge>memory: {a.memory_scope ?? "agent"}</Badge>
                {a.thinking && a.thinking !== "inherit" && <Badge tone={a.thinking === "on" ? "warn" : "neutral"}>thinking {a.thinking}</Badge>}
                {a.effort && a.effort !== "inherit" && <Badge>effort {a.effort}</Badge>}
                {a.max_steps != null && <Badge>{a.max_steps} steps</Badge>}
                {a.temperature != null && <Badge>T {a.temperature}</Badge>}
                {a.model && <Badge tone="accent">{a.model}</Badge>}
              </div>
              {(a.allowed_domains ?? []).length > 0 && (
                <p className="truncate text-xs text-muted" title={(a.allowed_domains ?? []).join(", ")}>Domains: {truncate((a.allowed_domains ?? []).join(", "), 80)}</p>
              )}
            </div>
            <div className="flex justify-between gap-2 border-t border-line px-3 py-2">
              <Button size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />} onClick={() => setRunning(a)}>Run now</Button>
              <div className="flex gap-1">
                <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(a)}>Edit</Button>
                <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} disabled={a.is_default} title={a.is_default ? "The default agent cannot be deleted" : "Delete"} onClick={() => setDel(a)}>Delete</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <AgentForm open={creating || editing !== null} agent={editing} onClose={() => { setCreating(false); setEditing(null); }} />
      <RunNowDialog agent={running} onClose={() => setRunning(null)} />
      <ConfirmDialog open={del !== null} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.id)} loading={remove.isPending} title="Delete agent?" message={<>“{del?.name}” and its configuration will be removed. Schedules that use it may stop working.</>} />
    </Page>
  );
}

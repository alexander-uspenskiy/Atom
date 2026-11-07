import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { invalidate, useSchedules } from "../api/hooks";
import type { Schedule } from "../api/types";
import { Page } from "../components/Page";
import { ScheduleForm } from "../components/ScheduleForm";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { Button, IconButton } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { describeTrigger } from "../lib/schedule";
import { errMsg, fmtDateTime, fmtRelative } from "../lib/format";

const ASK_PROMPT = "I'd like to create a schedule. Every weekday at 8:00 please ";

export default function SchedulesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const q = useSchedules();
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [creating, setCreating] = useState(false);
  const [del, setDel] = useState<Schedule | null>(null);

  const toggle = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) => api.toggleSchedule(v.id, v.enabled),
    onSuccess: () => invalidate(qc, "schedules", "status"),
    onError: (e) => toast.error(errMsg(e)),
  });
  const runNow = useMutation({
    mutationFn: (id: string) => api.runSchedule(id),
    onSuccess: (r) => {
      invalidate(qc, "runs", "status", "schedules");
      toast.success("Run started");
      nav(`/runs/${encodeURIComponent(r.run_id)}`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSchedule(id),
    onSuccess: () => {
      invalidate(qc, "schedules", "status");
      toast.success("Schedule deleted");
      setDel(null);
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  return (
    <Page
      title="Schedules"
      subtitle="Run agents automatically on a cron, interval or one-off trigger"
      actions={
        <>
          <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={() => nav("/chat", { state: { prompt: ASK_PROMPT } })}>
            Ask the assistant to create one
          </Button>
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New schedule</Button>
        </>
      }
    >
      <Card className="overflow-hidden">
        {q.isLoading && <Loading />}
        {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
        {q.data && q.data.length === 0 && (
          <EmptyState
            icon={CalendarClock}
            title="No schedules yet"
            hint="Describe what you want in chat, or create one manually."
            action={<Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={() => nav("/chat", { state: { prompt: ASK_PROMPT } })}>Ask the assistant</Button>}
          />
        )}
        {q.data && q.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm">
              <thead className="border-b border-line bg-surface2/60 text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Agent</th>
                  <th className="px-2 py-1.5 font-medium">Trigger</th>
                  <th className="px-2 py-1.5 font-medium">Next run</th>
                  <th className="px-2 py-1.5 font-medium">Last</th>
                  <th className="px-2 py-1.5 font-medium">On</th>
                  <th className="px-3 py-1.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((s) => (
                  <tr key={s.id} className="border-b border-line last:border-0 hover:bg-surface2/60">
                    <td className="max-w-[16rem] px-3 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-medium">{s.name}</span>
                        {s.created_by === "assistant" && <Badge tone="accent">assistant</Badge>}
                      </div>
                      <div className="truncate text-xs text-muted">{s.task}</div>
                    </td>
                    <td className="px-2 py-1.5 text-muted">{s.agent_name ?? "—"}</td>
                    <td className="px-2 py-1.5">
                      <div>{describeTrigger(s.trigger)}</div>
                      <div className="text-xs text-muted">{s.timezone}</div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5">
                      {s.enabled && s.next_run_at ? (
                        <>
                          <div>{fmtDateTime(s.next_run_at)}</div>
                          <div className="text-xs text-muted">{fmtRelative(s.next_run_at)}</div>
                        </>
                      ) : (
                        <span className="text-muted">{s.enabled ? "—" : "paused"}</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {s.last_status ? (
                        <Link to={s.last_run_id ? `/runs/${encodeURIComponent(s.last_run_id)}` : "/runs"} className="inline-flex flex-col gap-0.5">
                          <StatusBadge status={s.last_status} />
                          <span className="text-xs text-muted">{fmtRelative(s.last_run_at)} · {s.run_count ?? 0} runs</span>
                        </Link>
                      ) : (
                        <span className="text-muted">never</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      <Switch checked={s.enabled} label={`${s.enabled ? "Disable" : "Enable"} ${s.name}`} onChange={(enabled) => toggle.mutate({ id: s.id, enabled })} />
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="flex justify-end gap-0.5">
                        <IconButton label="Run now" disabled={runNow.isPending} onClick={() => runNow.mutate(s.id)}><Play className="h-3.5 w-3.5" /></IconButton>
                        <IconButton label="Edit" onClick={() => setEditing(s)}><Pencil className="h-3.5 w-3.5" /></IconButton>
                        <IconButton label="Delete" className="hover:text-err" onClick={() => setDel(s)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <ScheduleForm open={creating || editing !== null} schedule={editing} onClose={() => { setCreating(false); setEditing(null); }} />
      <ConfirmDialog
        open={del !== null}
        onClose={() => setDel(null)}
        onConfirm={() => del && remove.mutate(del.id)}
        loading={remove.isPending}
        title="Delete schedule?"
        message={<>“{del?.name}” will stop running. Past runs are kept.</>}
      />
    </Page>
  );
}

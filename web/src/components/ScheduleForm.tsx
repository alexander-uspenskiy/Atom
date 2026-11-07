import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { invalidate, useAgents } from "../api/hooks";
import type { Schedule, ScheduleInput, ScheduleTrigger } from "../api/types";
import { CRON_PRESETS, localTimezone, timezones } from "../lib/schedule";
import { errMsg, fmtDateTime } from "../lib/format";
import { useQuery } from "@tanstack/react-query";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { Field } from "./ui/Fields";
import { Select } from "./ui/Select";
import { Spinner } from "./ui/Spinner";
import { Switch } from "./ui/Switch";
import { Tabs } from "./ui/Tabs";
import { useToast } from "./ui/Toast";

type TType = "cron" | "interval" | "once";
const UNITS = [
  { value: "60", label: "minutes" },
  { value: "3600", label: "hours" },
  { value: "86400", label: "days" },
];

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

function initialInterval(t?: ScheduleTrigger): { n: string; unit: string } {
  if (t?.type !== "interval") return { n: "1", unit: "3600" };
  for (const u of [86400, 3600, 60]) if (t.seconds % u === 0) return { n: String(t.seconds / u), unit: String(u) };
  return { n: String(Math.round(t.seconds / 60) || 1), unit: "60" };
}

export function ScheduleForm({ open, onClose, schedule }: { open: boolean; onClose: () => void; schedule?: Schedule | null }) {
  const qc = useQueryClient();
  const toast = useToast();
  const agents = useAgents();
  const tzs = useMemo(timezones, []);
  const edit = !!schedule;

  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [task, setTask] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [tz, setTz] = useState(localTimezone());
  const [enabled, setEnabled] = useState(true);
  const [ttype, setTtype] = useState<TType>("cron");
  const [cron, setCron] = useState("0 8 * * 1-5");
  const [ivN, setIvN] = useState("1");
  const [ivUnit, setIvUnit] = useState("3600");
  const [onceAt, setOnceAt] = useState("");

  useEffect(() => {
    if (!open) return;
    const t = schedule?.trigger;
    setName(schedule?.name ?? "");
    setAgentId(schedule?.agent_id ?? "");
    setTask(schedule?.task ?? "");
    setStartUrl(schedule?.start_url ?? "");
    setTz(schedule?.timezone ?? localTimezone());
    setEnabled(schedule?.enabled ?? true);
    setTtype(t?.type ?? "cron");
    setCron(t?.type === "cron" ? t.expr : "0 8 * * 1-5");
    const iv = initialInterval(t);
    setIvN(iv.n);
    setIvUnit(iv.unit);
    setOnceAt(t?.type === "once" ? t.at.slice(0, 16) : "");
  }, [open, schedule]);

  useEffect(() => {
    if (open && !agentId && agents.data?.length) setAgentId((agents.data.find((a) => a.is_default) ?? agents.data[0]).id);
  }, [open, agentId, agents.data]);

  const trigger = useMemo<ScheduleTrigger | null>(() => {
    if (ttype === "cron") return cron.trim() ? { type: "cron", expr: cron.trim().replace(/\s+/g, " ") } : null;
    if (ttype === "interval") {
      const n = Number(ivN);
      return n > 0 ? { type: "interval", seconds: Math.round(n * Number(ivUnit)) } : null;
    }
    return onceAt ? { type: "once", at: onceAt.length === 16 ? `${onceAt}:00` : onceAt } : null;
  }, [ttype, cron, ivN, ivUnit, onceAt]);

  const dTrigger = useDebounced(trigger, 350);
  const dTz = useDebounced(tz, 350);
  const preview = useQuery({
    queryKey: ["schedule-preview", dTrigger, dTz],
    queryFn: ({ signal }) => api.previewSchedule(dTrigger as ScheduleTrigger, dTz, 5, signal),
    enabled: open && !!dTrigger,
    retry: false,
    staleTime: 30000,
  });

  const save = useMutation({
    mutationFn: (body: ScheduleInput) => (edit && schedule ? api.updateSchedule(schedule.id, body) : api.createSchedule(body)),
    onSuccess: () => {
      invalidate(qc, "schedules", "status");
      toast.success(edit ? "Schedule updated" : "Schedule created");
      onClose();
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const valid = name.trim() && task.trim() && trigger && agentId && !(preview.data && preview.data.error);
  const submit = () => {
    if (!valid || !trigger) return;
    save.mutate({ name: name.trim(), agent_id: agentId, task: task.trim(), start_url: startUrl.trim() || null, trigger, timezone: tz, enabled });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      wide
      title={edit ? "Edit schedule" : "New schedule"}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={submit}>{edit ? "Save" : "Create"}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="sch-name"><input id="sch-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning HN digest" /></Field>
          <Field label="Agent" htmlFor="sch-agent">
            <Select id="sch-agent" value={agentId} onChange={(e) => setAgentId(e.target.value)} options={(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))} />
          </Field>
        </div>
        <Field label="Task" htmlFor="sch-task">
          <textarea id="sch-task" className="input h-24 resize-y" value={task} onChange={(e) => setTask(e.target.value)} placeholder="Report the top 5 Hacker News stories" />
        </Field>
        <Field label="Start URL (optional)" htmlFor="sch-url">
          <input id="sch-url" className="input" value={startUrl} onChange={(e) => setStartUrl(e.target.value)} placeholder="https://news.ycombinator.com" />
        </Field>

        <div className="rounded-lg border border-line p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <Tabs<TType> items={[{ value: "cron", label: "Cron" }, { value: "interval", label: "Interval" }, { value: "once", label: "Once" }]} value={ttype} onChange={setTtype} />
            <div className="w-64">
              <Select aria-label="Timezone" value={tz} onChange={(e) => setTz(e.target.value)} options={tzs.includes(tz) ? tzs : [tz, ...tzs]} />
            </div>
          </div>
          {ttype === "cron" && (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {CRON_PRESETS.map((p) => (
                  <button
                    key={p.expr}
                    type="button"
                    onClick={() => setCron(p.expr)}
                    className={`rounded-full border px-2 py-0.5 text-xs ${cron.trim() === p.expr ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:text-fg"}`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <Field label="Cron expression (m h dom mon dow)" htmlFor="sch-cron">
                <input id="sch-cron" className="input font-mono" value={cron} onChange={(e) => setCron(e.target.value)} spellCheck={false} />
              </Field>
            </div>
          )}
          {ttype === "interval" && (
            <Field label="Run every" htmlFor="sch-iv">
              <div className="flex gap-2">
                <input id="sch-iv" type="number" min={1} className="input w-28" value={ivN} onChange={(e) => setIvN(e.target.value)} />
                <Select aria-label="Unit" className="w-32" value={ivUnit} onChange={(e) => setIvUnit(e.target.value)} options={UNITS} />
              </div>
            </Field>
          )}
          {ttype === "once" && (
            <Field label={`Run at (local time in ${tz})`} htmlFor="sch-once">
              <input id="sch-once" type="datetime-local" className="input w-56" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} />
            </Field>
          )}

          <div className="mt-3 rounded-md bg-surface2 px-3 py-2 text-xs" aria-live="polite" data-testid="schedule-preview">
            {!trigger && <span className="text-muted">Enter a trigger to see a preview.</span>}
            {trigger && preview.isFetching && <Spinner label="Checking…" />}
            {trigger && !preview.isFetching && preview.error && <span className="text-err">{errMsg(preview.error)}</span>}
            {trigger && !preview.isFetching && preview.data?.error && <span className="text-err">{preview.data.error}</span>}
            {trigger && !preview.isFetching && preview.data && !preview.data.error && (
              <>
                <div className="font-medium">{preview.data.description}</div>
                <ul className="mt-1 space-y-0.5 text-muted">
                  {(preview.data.next ?? []).map((n) => (
                    <li key={n} className="tabular-nums">{fmtDateTime(Date.parse(n) / 1000)} <span className="text-muted/70">({n})</span></li>
                  ))}
                  {(preview.data.next ?? []).length === 0 && <li>No upcoming runs.</li>}
                </ul>
              </>
            )}
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <Switch checked={enabled} onChange={setEnabled} label="Enabled" /> Enabled
        </label>
      </div>
    </Dialog>
  );
}

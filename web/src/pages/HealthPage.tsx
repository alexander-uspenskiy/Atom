import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { HeartPulse, Upload } from "lucide-react";
import { Page } from "../components/Page";
import { Button } from "../components/ui/Button";
import { Card, CardHeader, Stat } from "../components/ui/Card";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { Tabs } from "../components/ui/Tabs";
import { useChartColors } from "../lib/theme";
import { fmtDateTime, fmtInt } from "../lib/format";

interface Day { day: string; active_energy?: number; basal_energy?: number; total_energy?: number; steps?: number; exercise?: number; distance?: number; dietary_energy?: number }
interface Workout { kind: string; start_ts: number; day: string; minutes: number; kcal: number; km: number; source: string }
interface Summary {
  days: number; today: string; series: Day[]; weight: { day: string; value: number }[]; workouts: Workout[];
  points: Record<string, { day: string; value: number }[]>;
  averages: Record<string, number | null>; today_values: Day; has_data: boolean; last_update: number | null;
}
type Range = "7" | "30" | "90";

async function json<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail || `${res.status} ${res.statusText}`);
  return body as T;
}

const n = (v: number | null | undefined, unit = "") => (v == null ? "—" : `${fmtInt(Math.round(v))}${unit}`);

function Charts({ d }: { d: Summary }) {
  const c = useChartColors();
  const axis = { stroke: c.muted, fontSize: 11, tickLine: false, axisLine: { stroke: c.line } } as const;
  const tip = {
    contentStyle: { background: c.surface, border: `1px solid ${c.line}`, borderRadius: 8, fontSize: 12, color: c.fg },
    labelStyle: { color: c.fg, fontWeight: 600 }, cursor: { fill: c.line, opacity: 0.3 },
  };
  const rows = d.series.map((x) => ({ ...x, label: x.day.slice(5) }));
  const hasEnergy = rows.some((r) => r.active_energy != null || r.basal_energy != null);
  const hasSteps = rows.some((r) => r.steps != null);
  const w = d.weight.map((x) => ({ ...x, label: x.day.slice(5) }));
  const hr = (d.points.resting_hr ?? []).map((x) => ({ ...x, label: x.day.slice(5) }));
  const box = (title: string, ok: boolean, chart: JSX.Element) => (
    <Card>
      <CardHeader title={title} />
      <div className="h-64 px-2 py-3">{ok ? chart : <EmptyState title="No data in this range" />}</div>
    </Card>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {box("Energy spent (kcal)", hasEnergy,
        <ResponsiveContainer><BarChart data={rows}><CartesianGrid stroke={c.line} vertical={false} /><XAxis dataKey="label" {...axis} /><YAxis {...axis} width={44} />
          <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="basal_energy" name="Resting" stackId="e" fill={c.muted} />
          <Bar dataKey="active_energy" name="Active" stackId="e" fill={c.accent} /></BarChart></ResponsiveContainer>)}
      {box("Steps", hasSteps,
        <ResponsiveContainer><BarChart data={rows}><CartesianGrid stroke={c.line} vertical={false} /><XAxis dataKey="label" {...axis} /><YAxis {...axis} width={44} />
          <Tooltip {...tip} /><Bar dataKey="steps" name="Steps" fill={c.accent} /></BarChart></ResponsiveContainer>)}
      {box("Weight (kg)", w.length > 0,
        <ResponsiveContainer><LineChart data={w}><CartesianGrid stroke={c.line} vertical={false} /><XAxis dataKey="label" {...axis} /><YAxis {...axis} width={44} domain={["auto", "auto"]} />
          <Tooltip {...tip} /><Line type="monotone" dataKey="value" name="kg" stroke={c.accent} dot={w.length < 40} strokeWidth={2} /></LineChart></ResponsiveContainer>)}
      {box("Resting heart rate (bpm)", hr.length > 0,
        <ResponsiveContainer><LineChart data={hr}><CartesianGrid stroke={c.line} vertical={false} /><XAxis dataKey="label" {...axis} /><YAxis {...axis} width={44} domain={["auto", "auto"]} />
          <Tooltip {...tip} /><Line type="monotone" dataKey="value" name="bpm" stroke={c.accent} dot={hr.length < 40} strokeWidth={2} /></LineChart></ResponsiveContainer>)}
    </div>
  );
}

function Connect() {
  const qc = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const token = useQuery({ queryKey: ["health-token"], queryFn: () => fetch("/api/health/token").then((r) => json<{ token: string }>(r)) });
  const imp = useMutation({
    mutationFn: async (f: File) => json<{ records: number; points: number; workouts: number; days: number }>(
      await fetch("/api/health/import", { method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["health"] }),
  });
  const rotate = useMutation({
    mutationFn: async () => json<{ token: string }>(await fetch("/api/health/token/rotate", { method: "POST" })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["health-token"] }),
  });
  const url = `${location.origin}/api/health/ingest`;
  return (
    <Card>
      <CardHeader title="Get data from Apple Health" />
      <div className="space-y-4 p-4 text-sm">
        <div>
          <p className="font-medium">1. One-time import (full history)</p>
          <p className="text-muted">On the iPhone: Health app → your profile picture → Export All Health Data. Send the <code>export.zip</code> to this Mac (AirDrop) and upload it here. Large files take a minute; re-uploading is safe.</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <input ref={file} type="file" accept=".zip,.xml" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) imp.mutate(f); e.target.value = ""; }} />
            <Button onClick={() => file.current?.click()} disabled={imp.isPending}><Upload size={14} /> {imp.isPending ? "Importing…" : "Upload export.zip"}</Button>
            {imp.data && <span className="text-ok">Imported {fmtInt(imp.data.records)} records, {imp.data.workouts} workouts, {imp.data.points} readings over {imp.data.days} days.</span>}
            {imp.error && <span className="text-err">{(imp.error as Error).message}</span>}
          </div>
        </div>
        <div>
          <p className="font-medium">2. Ongoing sync from the phone</p>
          <p className="text-muted">
            An iOS Shortcut (or a Health-export app) can POST JSON to the URL below with the header <code>Authorization: Bearer &lt;token&gt;</code>. Body:
          </p>
          <pre className="mt-1 overflow-x-auto rounded-md bg-surface2 p-2 text-xs">{`{"samples":[
  {"type":"active_energy","date":"2026-11-13","value":640,"unit":"kcal"},
  {"type":"basal_energy","date":"2026-11-13","value":1720},
  {"type":"steps","date":"2026-11-13","value":9120},
  {"type":"weight","start":"2026-11-13T07:05:00+01:00","value":81.2,"unit":"kg"}
]}`}</pre>
          <p className="mt-1 text-muted">Types: active_energy, basal_energy, steps, distance, exercise, dietary_energy (daily totals), weight, body_fat, resting_hr, hrv (readings), workout. Reaching the Mac from the phone needs Tailscale or LAN plus <code>ATOM_ALLOWED_HOSTS</code> (see docs/VERSIONS.md 0.15.0).</p>
          <div className="mt-2 space-y-1 text-xs">
            <div>URL: <code className="select-all">{url}</code></div>
            <div className="flex items-center gap-2">Token: <code className="select-all break-all">{token.data?.token ?? "…"}</code>
              <Button variant="ghost" onClick={() => { if (confirm("Replace the token? Existing shortcuts stop working until updated.")) rotate.mutate(); }}>Regenerate</Button></div>
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function HealthPage() {
  const [range, setRange] = useState<Range>("30");
  const q = useQuery({ queryKey: ["health", range], queryFn: () => fetch(`/api/health/summary?days=${range}`).then((r) => json<Summary>(r)), refetchInterval: 30000 });
  const d = q.data;
  const t = d?.today_values;
  const latestW = d?.weight.length ? d.weight[d.weight.length - 1] : null;
  const todayTotal = t ? (t.total_energy ?? t.active_energy ?? null) : null;
  return (
    <Page
      title="Health"
      subtitle={d?.last_update ? `Apple Health · last data stored ${fmtDateTime(d.last_update)}` : "Apple Health"}
      actions={<Tabs<Range> value={range} onChange={setRange} items={[{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }]} />}
    >
      {q.isLoading && <Loading />}
      {q.error && !d && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {d && (
        <div className="mx-auto max-w-6xl space-y-4">
          {!d.has_data && <Card><EmptyState icon={HeartPulse} title="No health data yet" hint="Import your Apple Health export below." /></Card>}
          {d.has_data && (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Stat label="Spent today" value={n(todayTotal, " kcal")} sub={`${n(t?.active_energy)} active · ${n(t?.basal_energy)} resting`} />
                <Stat label="Avg spent / day" value={n(d.averages.total_energy ?? d.averages.active_energy, " kcal")} sub={`${n(d.averages.active_energy)} active`} />
                <Stat label="Steps today" value={n(t?.steps)} sub={`avg ${n(d.averages.steps)} / day`} />
                <Stat label="Weight" value={latestW ? `${latestW.value} kg` : "—"} sub={latestW?.day} />
              </div>
              <Charts d={d} />
              <Card>
                <CardHeader title="Workouts" />
                {d.workouts.length === 0 ? <EmptyState title="No workouts in this range" /> : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs text-muted"><tr><th className="px-4 py-2">When</th><th>Type</th><th>Minutes</th><th>kcal</th><th>km</th><th>Source</th></tr></thead>
                      <tbody>{d.workouts.map((w) => (
                        <tr key={`${w.source}${w.kind}${w.start_ts}`} className="border-t border-line">
                          <td className="px-4 py-2">{fmtDateTime(w.start_ts)}</td><td>{w.kind}</td><td>{Math.round(w.minutes)}</td>
                          <td>{Math.round(w.kcal)}</td><td>{w.km ? w.km.toFixed(1) : "—"}</td><td className="text-muted">{w.source}</td></tr>))}</tbody>
                    </table>
                  </div>
                )}
              </Card>
            </>
          )}
          <Connect />
        </div>
      )}
    </Page>
  );
}

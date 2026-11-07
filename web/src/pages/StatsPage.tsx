import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3 } from "lucide-react";
import { useStats } from "../api/hooks";
import { Page } from "../components/Page";
import { Card, CardHeader, Stat } from "../components/ui/Card";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { Tabs } from "../components/ui/Tabs";
import { StatusBadge } from "../components/ui/Badge";
import { useChartColors } from "../lib/theme";
import { fmtDuration, fmtInt, fmtPct, fmtTokens, fmtTps, truncate } from "../lib/format";

type Range = "1" | "7" | "30";

function ChartCard({ title, children, empty }: { title: string; children: ReactNode; empty: boolean }) {
  return (
    <Card>
      <CardHeader title={title} />
      <div className="h-64 px-2 py-3">{empty ? <EmptyState title="No data in this range" /> : children}</div>
    </Card>
  );
}

export default function StatsPage() {
  const [range, setRange] = useState<Range>("7");
  const q = useStats(Number(range));
  const c = useChartColors();
  const d = q.data;
  const byDay = (d?.by_day ?? []).map((x) => {
    const input = x.input ?? 0;
    const cached = Math.min(x.cached ?? 0, input);
    return { day: x.day, label: x.day.slice(5), runs: x.runs ?? 0, cached, processed: Math.max(0, input - cached), output: x.output ?? 0, llm: x.llm_seconds ?? 0 };
  });
  const axis = { stroke: c.muted, fontSize: 11, tickLine: false, axisLine: { stroke: c.line } } as const;
  const tip = {
    contentStyle: { background: c.surface, border: `1px solid ${c.line}`, borderRadius: 8, fontSize: 12, color: c.fg },
    labelStyle: { color: c.fg, fontWeight: 600 },
    cursor: { fill: c.line, opacity: 0.3 },
  };

  return (
    <Page
      title="Stats"
      subtitle="Throughput, cache efficiency and run outcomes"
      actions={<Tabs<Range> value={range} onChange={setRange} items={[{ value: "1", label: "1 day" }, { value: "7", label: "7 days" }, { value: "30", label: "30 days" }]} />}
    >
      {q.isLoading && <Loading />}
      {q.error && !d && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {d && (
        <div className="mx-auto max-w-6xl space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Runs" value={fmtInt(d.runs?.total)} sub={`${d.runs?.done ?? 0} done · ${d.runs?.failed ?? 0} failed · ${d.runs?.budget ?? 0} budget · ${d.runs?.stopped ?? 0} stopped`} />
            <Stat label="Success rate" value={fmtPct(d.runs?.success_rate)} tone={(d.runs?.success_rate ?? 1) < 0.5 ? "err" : undefined} />
            <Stat label="Input tokens" value={fmtTokens(d.tokens?.input)} sub={`${fmtTokens(d.tokens?.processed)} processed`} />
            <Stat label="Output tokens" value={fmtTokens(d.tokens?.output)} />
            <Stat label="Cache hit rate" value={fmtPct(d.tokens?.cache_hit_rate)} sub={`${fmtTokens(d.tokens?.cached)} cached`} />
            <Stat label="Decode speed" value={fmtTps(d.timing?.avg_decode_tps)} sub="avg" />
            <Stat label="Prefill speed" value={fmtTps(d.timing?.avg_prefill_tps)} sub="avg" />
            <Stat label="Avg wall time" value={fmtDuration(d.timing?.avg_wall_s)} sub={`${fmtDuration(d.timing?.avg_llm_s_per_step)} LLM / step`} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Tokens per day" empty={byDay.length === 0}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byDay} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" {...axis} />
                  <YAxis {...axis} tickFormatter={(v: number) => fmtTokens(v)} width={44} />
                  <Tooltip {...tip} formatter={(v: number, n: string) => [fmtInt(v), n]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="cached" name="Input (cached)" stackId="in" fill={c.ok} isAnimationActive={false} />
                  <Bar dataKey="processed" name="Input (processed)" stackId="in" fill={c.info} isAnimationActive={false} />
                  <Bar dataKey="output" name="Output" stackId="in" fill={c.accent} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            <ChartCard title="Runs per day" empty={byDay.length === 0}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byDay} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" {...axis} />
                  <YAxis {...axis} allowDecimals={false} width={32} />
                  <Tooltip {...tip} />
                  <Bar dataKey="runs" name="Runs" fill={c.accent} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
          <ChartCard title="LLM seconds per day" empty={byDay.length === 0}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={byDay} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" {...axis} />
                <YAxis {...axis} width={40} tickFormatter={(v: number) => `${Math.round(v)}s`} />
                <Tooltip {...tip} formatter={(v: number) => [fmtDuration(v), "LLM time"]} />
                <Line type="monotone" dataKey="llm" name="LLM time" stroke={c.warn} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="overflow-hidden">
              <CardHeader title="By agent" />
              {(d.by_agent ?? []).length === 0 ? <EmptyState title="No agent activity" /> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b border-line text-left text-xs text-muted">
                      <tr><th className="px-3 py-1.5 font-medium">Agent</th><th className="px-2 font-medium text-right">Runs</th><th className="px-2 font-medium text-right">Success</th><th className="px-2 font-medium text-right">In / out</th><th className="px-3 font-medium text-right">Avg time</th></tr>
                    </thead>
                    <tbody>
                      {(d.by_agent ?? []).map((a, i) => (
                        <tr key={a.agent_id ?? i} className="border-b border-line last:border-0">
                          <td className="px-3 py-1.5">{a.agent_name ?? a.agent_id ?? "—"}</td>
                          <td className="px-2 text-right tabular-nums">{a.runs ?? 0}</td>
                          <td className="px-2 text-right tabular-nums">{fmtPct(a.success_rate)}</td>
                          <td className="px-2 text-right tabular-nums">{fmtTokens(a.input)} / {fmtTokens(a.output)}</td>
                          <td className="px-3 text-right tabular-nums">{fmtDuration(a.avg_wall_s)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
            <Card>
              <CardHeader title="Slowest runs" />
              {(d.slowest_runs ?? []).length === 0 ? <EmptyState title="No runs yet" /> : (
                (d.slowest_runs ?? []).map((r) => (
                  <Link key={r.id} to={`/runs/${encodeURIComponent(r.id)}`} className="flex items-center gap-2 border-b border-line px-3 py-1.5 last:border-0 hover:bg-surface2">
                    <span className="min-w-0 flex-1 truncate text-sm">{truncate(r.task, 90) || r.id}</span>
                    <StatusBadge status={r.status} success={r.success} />
                    <span className="w-14 text-right text-xs font-medium tabular-nums">{fmtDuration(r.wall_seconds)}</span>
                  </Link>
                ))
              )}
            </Card>
          </div>
          {byDay.length === 0 && !q.isFetching && (d.runs?.total ?? 0) === 0 && (
            <p className="flex items-center justify-center gap-1.5 text-xs text-muted"><BarChart3 className="h-3.5 w-3.5" /> No runs recorded in the selected range.</p>
          )}
        </div>
      )}
    </Page>
  );
}

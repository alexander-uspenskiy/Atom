import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Plug } from "lucide-react";
import { Page } from "../components/Page";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { SearchInput } from "../components/ui/Fields";
import { Select } from "../components/ui/Select";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { cn } from "../lib/cn";
import { fmtDateTime, fmtRelative } from "../lib/format";

interface Call { id: string; ts: number; method: string; path: string; query: string; status: number; ms: number; client: string; ip: string; run_id: string }
interface Calls { items: Call[]; total: number; callers?: string[] }

const PAGE = 50;
const METHODS = ["", "GET", "POST", "PUT", "DELETE"];
const BASE_CLIENTS = ["external", "token", "telegram", "ui"];

async function fetchCalls(q: string, method: string, client: string, failed: boolean, offset: number): Promise<Calls> {
  const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  if (q) p.set("q", q);
  if (method) p.set("method", method);
  if (client) p.set("client", client);
  if (failed) p.set("failed", "true");
  const res = await fetch(`/api/calls?${p}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

const statusStyle = (s: number) =>
  s >= 500 ? "bg-red-500/15 text-red-600 dark:text-red-400"
  : s >= 400 ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
  : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400";

export default function CallsPage() {
  const [q, setQ] = useState("");
  const [method, setMethod] = useState("");
  const [client, setClient] = useState("");
  const [failed, setFailed] = useState(false);
  const [offset, setOffset] = useState(0);
  const calls = useQuery({ queryKey: ["calls", q, method, client, failed, offset], queryFn: () => fetchCalls(q, method, client, failed, offset), refetchInterval: 5000 });
  const total = calls.data?.total ?? 0;
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setOffset(0); };

  return (
    <Page
      title="API calls"
      subtitle={calls.data ? `${total} call${total === 1 ? "" : "s"} · dashboard reads are not logged` : undefined}
      actions={
        <>
          <SearchInput className="w-52" value={q} onChange={reset(setQ)} placeholder="Search path or run…" />
          <Select aria-label="Method" className="w-28" value={method} onChange={(e) => reset(setMethod)(e.target.value)} options={METHODS.map((m) => ({ value: m, label: m || "All methods" }))} />
          <Select aria-label="Caller" className="w-32" value={client} onChange={(e) => reset(setClient)(e.target.value)} options={["", ...Array.from(new Set([...BASE_CLIENTS, ...(calls.data?.callers ?? [])]))].map((c) => ({ value: c, label: c || "All callers" }))} />
          <Button variant={failed ? "primary" : "ghost"} onClick={() => reset(setFailed)(!failed)}>Errors only</Button>
        </>
      }
    >
      <Card className="overflow-hidden">
        {calls.isLoading && <Loading />}
        {calls.error && !calls.data && <ErrorState error={calls.error} onRetry={() => void calls.refetch()} />}
        {calls.data && calls.data.items.length === 0 && (
          <EmptyState icon={Plug} title="No calls" hint={q || method || client || failed ? "Try clearing the filters." : "Calls from scripts, Shortcuts and other clients appear here."} />
        )}
        {calls.data && calls.data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-left text-xs text-muted">
                <tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Call</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Time</th><th className="px-3 py-2">Caller</th><th className="px-3 py-2">Run</th></tr>
              </thead>
              <tbody>
                {calls.data.items.map((c) => (
                  <tr key={c.id} className="border-t border-line">
                    <td className="whitespace-nowrap px-3 py-2 text-muted" title={fmtDateTime(c.ts)}>{fmtRelative(c.ts)}</td>
                    <td className="px-3 py-2 font-mono text-xs"><span className="mr-2 font-semibold">{c.method}</span>{c.path}{c.query && <span className="text-muted">?{c.query}</span>}</td>
                    <td className="px-3 py-2"><span className={cn("rounded px-1.5 py-0.5 text-xs", statusStyle(c.status))}>{c.status}</span></td>
                    <td className="whitespace-nowrap px-3 py-2 text-muted">{c.ms < 1000 ? `${Math.round(c.ms)} ms` : `${(c.ms / 1000).toFixed(1)} s`}</td>
                    <td className="px-3 py-2 text-muted">{c.client}{c.ip && c.client !== "ui" ? ` · ${c.ip}` : ""}</td>
                    <td className="px-3 py-2">{c.run_id && <Link className="text-accent hover:underline" to={`/runs/${c.run_id}`}>{c.run_id}</Link>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {total > PAGE && (
        <div className="mt-3 flex items-center justify-between text-sm text-muted">
          <Button variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</Button>
          <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <Button variant="ghost" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Older</Button>
        </div>
      )}
    </Page>
  );
}

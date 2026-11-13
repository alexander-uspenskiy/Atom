import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Send } from "lucide-react";
import { Page } from "../components/Page";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { SearchInput } from "../components/ui/Fields";
import { Select } from "../components/ui/Select";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { cn } from "../lib/cn";
import { fmtDateTime } from "../lib/format";

interface InboxFile { id: string; name: string; kind: "image" | "document"; mime: string; size: number; url?: string; missing?: boolean }
interface InboxItem {
  id: string; ts: number; connector: string; chat_id: number | null; user_id: number | null; username: string; name: string;
  kind: string; text: string; file_name: string; status: string; note: string; files: InboxFile[];
}
interface Inbox { items: InboxItem[]; total: number }

const PAGE = 30;
const STATUSES = ["", "accepted", "command", "denied", "unsupported", "error"];
const STATUS_STYLE: Record<string, string> = {
  accepted: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  command: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  denied: "bg-red-500/15 text-red-600 dark:text-red-400",
  unsupported: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  error: "bg-red-500/15 text-red-600 dark:text-red-400",
};

async function fetchInbox(q: string, status: string, offset: number): Promise<Inbox> {
  const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  if (q) p.set("q", q);
  if (status) p.set("status", status);
  const res = await fetch(`/api/telegram/inbox?${p}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function FilePreview({ f }: { f: InboxFile }) {
  if (f.missing) return <span className="text-xs text-muted">attachment no longer available</span>;
  if (f.kind === "image") {
    return (
      <a href={f.url} target="_blank" rel="noreferrer">
        <img src={f.url} alt={f.name || "image"} loading="lazy" className="max-h-48 max-w-[16rem] rounded-md border border-line object-cover" />
      </a>
    );
  }
  return (
    <a href={f.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm hover:bg-surface2">
      <FileText size={16} /> <span className="truncate">{f.name || "document"}</span>
      <span className="text-xs text-muted">{Math.max(1, Math.round(f.size / 1024))} KB</span>
    </a>
  );
}

export default function TelegramPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const inbox = useQuery({ queryKey: ["telegram-inbox", q, status, offset], queryFn: () => fetchInbox(q, status, offset), refetchInterval: 5000 });
  const total = inbox.data?.total ?? 0;
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setOffset(0); };

  return (
    <Page
      title="Telegram inbox"
      subtitle={inbox.data ? `${total} message${total === 1 ? "" : "s"} sent to the bot` : undefined}
      actions={
        <>
          <SearchInput className="w-52" value={q} onChange={reset(setQ)} placeholder="Search messages…" />
          <Select aria-label="Status" className="w-36" value={status} onChange={(e) => reset(setStatus)(e.target.value)}
            options={STATUSES.map((s) => ({ value: s, label: s || "All statuses" }))} />
        </>
      }
    >
      {inbox.isLoading && <Loading />}
      {inbox.error && !inbox.data && <ErrorState error={inbox.error} onRetry={() => void inbox.refetch()} />}
      {inbox.data && inbox.data.items.length === 0 && (
        <Card><EmptyState icon={Send} title="No messages" hint={q || status ? "Try clearing the filters." : "Messages sent to the bot appear here."} /></Card>
      )}
      <div className="mx-auto flex max-w-3xl flex-col gap-3">
        {inbox.data?.items.map((m) => (
          <Card key={m.id} className="p-3">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
              <span className="font-medium text-fg">{m.name || m.username || m.user_id}</span>
              {m.username && <span>@{m.username}</span>}
              <span>{fmtDateTime(m.ts)}</span>
              <span className={cn("rounded px-1.5 py-0.5", STATUS_STYLE[m.status] ?? "bg-surface2")}>{m.status}</span>
              {m.kind !== "text" && <span className="rounded bg-surface2 px-1.5 py-0.5">{m.kind}</span>}
              {m.note && <span className="truncate">{m.note}</span>}
            </div>
            {m.text && <p className="whitespace-pre-wrap break-words text-sm">{m.text}</p>}
            {!m.text && m.files.length === 0 && <p className="text-sm italic text-muted">({m.kind}{m.file_name ? `: ${m.file_name}` : ""})</p>}
            {m.files.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{m.files.map((f) => <FilePreview key={f.id} f={f} />)}</div>}
          </Card>
        ))}
        {total > PAGE && (
          <div className="flex items-center justify-between text-sm text-muted">
            <Button variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</Button>
            <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <Button variant="ghost" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Older</Button>
          </div>
        )}
      </div>
    </Page>
  );
}

import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ExternalLink, FileText } from "lucide-react";
import { localFileUrl } from "../../api/client";
import type { ToolView } from "../../lib/chatState";
import { cn } from "../../lib/cn";

const IMG = "png|jpe?g|gif|webp";
const DOC = "pdf|txt|md|json|csv|log";
const PATH_RE = new RegExp(`/(?:Users|home|tmp|private|var|opt|Volumes)/[^\\s)"'\`<>\\\\]+\\.(?:${IMG}|${DOC})(?![\\w/])`, "gi");
const isImage = (p: string) => new RegExp(`\\.(?:${IMG})$`, "i").test(p);
const isPdf = (p: string) => /\.pdf$/i.test(p);
const base = (p: string) => p.slice(p.lastIndexOf("/") + 1);

/** Previewable file paths mentioned in a reply's text and tool results, in order, de-duplicated. */
export function findArtifacts(content: string, tools: ToolView[]): string[] {
  const texts = [content, ...tools.map((t) => (t.result == null ? "" : typeof t.result === "string" ? t.result : JSON.stringify(t.result)))];
  const seen = new Set<string>();
  for (const t of texts) for (const m of t.matchAll(PATH_RE)) seen.add(m[0]);
  return [...seen];
}

function TextPreview({ path }: { path: string }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    fetch(localFileUrl(path), { signal: ac.signal, headers: { Range: "bytes=0-8191" } })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((t) => setText(t.slice(0, 8000)))
      .catch((e) => { if (!ac.signal.aborted) setText(`Could not load preview (${e instanceof Error ? e.message : e}).`); });
    return () => ac.abort();
  }, [path]);
  return <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-t border-line px-3 py-2 font-mono text-xs">{text ?? "Loading…"}</pre>;
}

function DocCard({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-line bg-surface" data-testid="artifact-doc">
      <div className="flex items-center gap-2 px-2.5 py-1.5">
        <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
          <ChevronRight className={cn("h-3 w-3 shrink-0 text-muted transition-transform", open && "rotate-90")} aria-hidden />
          <FileText className="h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
          <span className="truncate text-xs font-medium" title={path}>{base(path)}</span>
        </button>
        <a href={localFileUrl(path)} target="_blank" rel="noreferrer noopener" className="text-muted hover:text-text" title="Open in new tab" aria-label={`Open ${base(path)}`}>
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
      {open && (isPdf(path)
        ? <iframe src={localFileUrl(path)} title={base(path)} className="h-96 w-full border-t border-line" />
        : <TextPreview path={path} />)}
    </div>
  );
}

/** Inline previews of files the assistant created or mentioned: images as thumbnails, documents as expandable cards. */
export function Artifacts({ content, tools }: { content: string; tools: ToolView[] }) {
  const paths = useMemo(() => findArtifacts(content, tools), [content, tools]);
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const shown = paths.filter((p) => !broken.has(p));
  if (!shown.length) return null;
  const imgs = shown.filter(isImage);
  const docs = shown.filter((p) => !isImage(p));
  return (
    <div className="space-y-2" data-testid="artifacts">
      {imgs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {imgs.map((p) => (
            <a key={p} href={localFileUrl(p)} target="_blank" rel="noreferrer noopener" title={`${base(p)} — open full size`} className="block overflow-hidden rounded-md border border-line bg-surface2">
              <img src={localFileUrl(p)} alt={base(p)} loading="lazy" className="max-h-64 max-w-full object-contain"
                onError={() => setBroken((s) => new Set(s).add(p))} />
            </a>
          ))}
        </div>
      )}
      {docs.map((p) => <DocCard key={p} path={p} />)}
    </div>
  );
}

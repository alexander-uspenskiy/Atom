import { useEffect, useState } from "react";
import { ChevronUp, Folder, FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import { errMsg } from "../../lib/format";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

/** Text field + "Browse…" dialog that walks the server's folders (the backend runs on this machine). */
export function FolderPicker({
  id, value, onChange, placeholder,
}: { id?: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState<{ path: string; parent: string | null; dirs: string[] } | null>(null);
  const [err, setErr] = useState("");

  const go = (p: string) => {
    setErr("");
    api.fsDirs(p).then(setCur, (e) => setErr(errMsg(e)));
  };
  useEffect(() => {
    if (open) go(value || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <div className="flex w-full max-w-md gap-2">
      <input id={id} className="input flex-1 font-mono text-xs" value={value} placeholder={placeholder ?? "Default (data/workspace)"}
        onChange={(e) => onChange(e.target.value)} spellCheck={false} />
      <Button type="button" onClick={() => setOpen(true)}><FolderOpen className="h-4 w-4" aria-hidden /> Browse…</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Choose a working folder"
        footer={<>
          {value && <Button type="button" onClick={() => { onChange(""); setOpen(false); }}>Use default</Button>}
          <Button type="button" onClick={() => setOpen(false)}>Cancel</Button>
          <Button type="button" disabled={!cur} onClick={() => { if (cur) onChange(cur.path); setOpen(false); }}>Select this folder</Button>
        </>}>
        <div className="space-y-2">
          <div className="break-all font-mono text-xs text-muted">{cur?.path ?? "…"}</div>
          {err && <div role="alert" className="text-sm text-red-500">{err}</div>}
          <ul className="max-h-72 overflow-auto rounded border border-border">
            {cur?.parent && (
              <li><button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-black/5 dark:hover:bg-white/5" onClick={() => go(cur.parent!)}>
                <ChevronUp className="h-4 w-4" aria-hidden /> ..
              </button></li>
            )}
            {cur?.dirs.map((d) => (
              <li key={d}><button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-black/5 dark:hover:bg-white/5" onClick={() => go(`${cur.path.replace(/\/$/, "")}/${d}`)}>
                <Folder className="h-4 w-4" aria-hidden /> {d}
              </button></li>
            ))}
            {cur && !cur.dirs.length && <li className="px-3 py-2 text-sm text-muted">No subfolders</li>}
          </ul>
        </div>
      </Dialog>
    </div>
  );
}

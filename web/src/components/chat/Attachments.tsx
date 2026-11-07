import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { FileText, ImagePlus, Loader2, Paperclip, X } from "lucide-react";
import { api } from "../../api/client";
import { errMsg } from "../../lib/format";
import { isDocFile, isImageFile, prepareImage } from "../../lib/images";
import { useStatus, useUploadInfo } from "../../api/hooks";
import { cn } from "../../lib/cn";
import { useToast } from "../ui/Toast";

export const MAX_ATTACHMENTS = 6;

export interface Attachment {
  key: string; name: string; kind: "image" | "document"; preview: string; status: "uploading" | "ready" | "error"; id?: string; error?: string;
}

export interface AttachmentsApi {
  items: Attachment[];
  ids: string[];            // uploaded and ready
  busy: boolean;            // something is still uploading
  add: (files: File[]) => void;
  remove: (key: string) => void;
  clear: () => void;
  load: (ids: string[]) => void;   // replace everything with already-uploaded files (editing a saved item)
}

/** File attachments for a composer (images and documents): validates, downscales images, uploads in the background, tracks status. */
export function useAttachments(): AttachmentsApi {
  const toast = useToast();
  const visionOk = useStatus().data?.llm?.vision !== false;
  const visionRef = useRef(visionOk);
  visionRef.current = visionOk;
  const [items, setItems] = useState<Attachment[]>([]);
  const itemsRef = useRef<Attachment[]>([]);
  itemsRef.current = items;
  const seq = useRef(0);

  useEffect(() => () => itemsRef.current.forEach((a) => URL.revokeObjectURL(a.preview)), []);

  const add = useCallback(
    (files: File[]) => {
      let accepted = files.filter((f) => isImageFile(f) || isDocFile(f));
      if (files.length && !accepted.length) toast.error("Supported files: images (PNG, JPEG, WebP, GIF), PDF, Word (.docx), Excel (.xlsx), CSV/TSV, Markdown and text.");
      if (!visionRef.current && accepted.some(isImageFile)) {
        toast.error("The model server was started without a vision projector (--mmproj), so it can't read images. Documents still work.");
        accepted = accepted.filter((f) => !isImageFile(f));
      }
      const room = MAX_ATTACHMENTS - itemsRef.current.length;
      if (accepted.length > room) toast.error(`You can attach up to ${MAX_ATTACHMENTS} files per message.`);
      for (const file of accepted.slice(0, Math.max(0, room))) {
        const key = `att-${++seq.current}`;
        const kind = isImageFile(file) ? "image" : "document";
        const item: Attachment = { key, name: file.name || "pasted image", kind, preview: kind === "image" ? URL.createObjectURL(file) : "", status: "uploading" };
        itemsRef.current = [...itemsRef.current, item];
        setItems(itemsRef.current);
        const patch = (p: Partial<Attachment>) => {
          itemsRef.current = itemsRef.current.map((a) => (a.key === key ? { ...a, ...p } : a));
          setItems(itemsRef.current);
        };
        void (async () => {
          try {
            const up = kind === "image" ? await api.uploadImage(await prepareImage(file), item.name) : await api.uploadFile(file);
            patch({ status: "ready", id: up.id });
          } catch (e) {
            patch({ status: "error", error: errMsg(e) });
            toast.error(errMsg(e));
          }
        })();
      }
    },
    [toast],
  );

  const remove = useCallback((key: string) => {
    const gone = itemsRef.current.find((a) => a.key === key);
    if (gone?.preview) URL.revokeObjectURL(gone.preview);
    itemsRef.current = itemsRef.current.filter((a) => a.key !== key);
    setItems(itemsRef.current);
  }, []);

  const clear = useCallback(() => {
    itemsRef.current.forEach((a) => URL.revokeObjectURL(a.preview));
    itemsRef.current = [];
    setItems([]);
  }, []);

  const load = useCallback((ids: string[]) => {
    itemsRef.current.forEach((a) => URL.revokeObjectURL(a.preview));
    itemsRef.current = ids.map((id, i) => ({ key: `saved-${i}-${id}`, name: "attached file", kind: "image" as const, preview: api.uploadUrl(id), status: "ready" as const, id }));
    setItems(itemsRef.current);
    ids.forEach((id) => void api.uploadInfo(id).then((u) => {          // documents have no thumbnail: show their name instead
      itemsRef.current = itemsRef.current.map((a) => (a.id === id ? { ...a, kind: u.kind, name: u.name || a.name, preview: u.kind === "image" ? a.preview : "" } : a));
      setItems(itemsRef.current);
    }, () => undefined));
  }, []);

  return {
    items,
    ids: items.filter((a) => a.status === "ready" && a.id).map((a) => a.id as string),
    busy: items.some((a) => a.status === "uploading"),
    add, remove, clear, load,
  };
}

/** Pasted images from the clipboard (screenshots etc.). Returns true when it consumed the event. */
export function imagesFromClipboard(e: React.ClipboardEvent): File[] {
  return Array.from(e.clipboardData?.files ?? []).filter(isImageFile);
}

/** Drag-and-drop handlers + "dragging" flag for a drop target. */
export function useDropImages(add: (f: File[]) => void, enabled: boolean) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  return {
    over: over && enabled,
    handlers: {
      onDragEnter: (e: DragEvent) => { if (enabled && hasFiles(e)) { depth.current++; setOver(true); } },
      onDragLeave: (e: DragEvent) => { if (enabled && hasFiles(e) && --depth.current <= 0) { depth.current = 0; setOver(false); } },
      onDragOver: (e: DragEvent) => { if (enabled && hasFiles(e)) e.preventDefault(); },
      onDrop: (e: DragEvent) => {
        depth.current = 0;
        setOver(false);
        if (!enabled || !hasFiles(e)) return;
        e.preventDefault();
        add(Array.from(e.dataTransfer.files));
      },
    },
  };
}

/** Full-area hint shown while files are dragged over a drop target (parent must be `relative`). */
export function DropOverlay({ show, label = "Drop files to attach" }: { show: boolean; label?: string }) {
  if (!show) return null;
  return (
    <div
      className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-accent/10 backdrop-blur-[1px]"
      data-testid="drop-overlay"
    >
      <span className="inline-flex items-center gap-2 rounded-md bg-surface px-3 py-1.5 text-sm font-medium text-accent shadow">
        <ImagePlus className="h-4 w-4" aria-hidden /> {label}
      </span>
    </div>
  );
}

export function AttachButton({ api: att, disabled, reason }: { api: AttachmentsApi; disabled?: boolean; reason?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const full = att.items.length >= MAX_ATTACHMENTS;
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf,.docx,.xlsx,.csv,.tsv,.md,.markdown,.txt,text/markdown,text/plain,text/csv"
        multiple
        hidden
        data-testid="attach-input"
        onChange={(e) => {
          att.add(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className="inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-xs text-muted transition-colors hover:bg-surface2 hover:text-fg disabled:opacity-50"
        disabled={disabled || full}
        title={disabled ? reason : full ? `Up to ${MAX_ATTACHMENTS} files` : "Attach images, PDF, Word, Excel, CSV, Markdown or text files (or paste / drop them)"}
        aria-label="Attach files"
        onClick={() => input.current?.click()}
      >
        <Paperclip className="h-3.5 w-3.5" aria-hidden /> Attach
      </button>
    </>
  );
}

export function AttachmentStrip({ api: att }: { api: AttachmentsApi }) {
  if (!att.items.length) return null;
  return (
    <ul className="flex flex-wrap gap-2 px-3 pt-2" aria-label="Attached files">
      {att.items.map((a) => (
        <li key={a.key} className={cn("group relative overflow-hidden rounded-md border", a.kind === "image" ? "h-16 w-16" : "flex h-16 max-w-[11rem] items-center gap-1.5 bg-surface2 px-2", a.status === "error" ? "border-err" : "border-line")}>
          {a.kind === "image" ? (
            <img src={a.preview} alt={a.name} className={cn("h-full w-full object-cover", a.status !== "ready" && "opacity-50")} />
          ) : (
            <>
              <FileText className={cn("h-5 w-5 shrink-0 text-muted", a.status !== "ready" && "opacity-50")} aria-hidden />
              <span className="line-clamp-2 break-all text-[11px] leading-tight" title={a.name}>{a.name}</span>
            </>
          )}
          {a.status === "uploading" && <Loader2 className="absolute inset-0 m-auto h-4 w-4 animate-spin text-fg" aria-label="Uploading" />}
          {a.status === "error" && <span className="absolute inset-x-0 bottom-0 bg-err px-1 text-center text-[10px] text-white" title={a.error}>failed</span>}
          <button
            type="button"
            aria-label={`Remove ${a.name}`}
            className="absolute right-0.5 top-0.5 rounded-full bg-bg/90 p-0.5 text-fg opacity-90 hover:bg-err hover:text-white"
            onClick={() => att.remove(a.key)}
          >
            <X className="h-3 w-3" />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Read-only view of already-uploaded files (chat bubbles, run page): image thumbnails and document chips. Click opens the file. */
export function ImageGrid({ ids, className, size = "md" }: { ids: string[]; className?: string; size?: "sm" | "md" }) {
  if (!ids.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)} data-testid="image-grid">
      {ids.map((id) => <UploadTile key={id} id={id} size={size} />)}
    </div>
  );
}

function UploadTile({ id, size }: { id: string; size: "sm" | "md" }) {
  const info = useUploadInfo(id).data;
  if (info?.kind === "document") {
    const meta = [info.pages ? `${info.pages} p.` : null, info.sheets ? `${info.sheets} sheet${info.sheets > 1 ? "s" : ""}` : null, info.rows != null ? `${info.rows} rows` : null, info.scanned ? "scanned" : null].filter(Boolean).join(" · ");
    return (
      <a href={api.uploadUrl(id)} target="_blank" rel="noreferrer" title={info.name}
         className="flex max-w-[14rem] items-center gap-1.5 rounded-md border border-line/60 bg-bg px-2 py-1.5 text-xs hover:bg-surface2">
        <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
        <span className="min-w-0"><span className="block truncate">{info.name || "document"}</span>{meta && <span className="block text-[10px] text-muted">{meta}</span>}</span>
      </a>
    );
  }
  if (!info) return <div className={cn("rounded-md border border-line/60 bg-bg", size === "sm" ? "h-16 w-16" : "h-24 w-24")} aria-hidden />;
  return (
    <a href={api.uploadUrl(id)} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-md border border-line/60 bg-bg">
      <img src={api.uploadUrl(id)} alt="Attached" loading="lazy" className={cn("w-auto object-cover", size === "sm" ? "h-16" : "max-h-48 max-w-full")} />
    </a>
  );
}

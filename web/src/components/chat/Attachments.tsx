import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { ImagePlus, Loader2, X } from "lucide-react";
import { api } from "../../api/client";
import { errMsg } from "../../lib/format";
import { isImageFile, prepareImage } from "../../lib/images";
import { cn } from "../../lib/cn";
import { useToast } from "../ui/Toast";

export const MAX_ATTACHMENTS = 6;

export interface Attachment {
  key: string; name: string; preview: string; status: "uploading" | "ready" | "error"; id?: string; error?: string;
}

export interface AttachmentsApi {
  items: Attachment[];
  ids: string[];            // uploaded and ready
  busy: boolean;            // something is still uploading
  add: (files: File[]) => void;
  remove: (key: string) => void;
  clear: () => void;
}

/** Image attachments for a composer: validates, downscales, uploads in the background, tracks status. */
export function useAttachments(): AttachmentsApi {
  const toast = useToast();
  const [items, setItems] = useState<Attachment[]>([]);
  const itemsRef = useRef<Attachment[]>([]);
  itemsRef.current = items;
  const seq = useRef(0);

  useEffect(() => () => itemsRef.current.forEach((a) => URL.revokeObjectURL(a.preview)), []);

  const add = useCallback(
    (files: File[]) => {
      const images = files.filter(isImageFile);
      if (files.length && !images.length) toast.error("Only image files can be attached (PNG, JPEG, WebP, GIF).");
      const room = MAX_ATTACHMENTS - itemsRef.current.length;
      if (images.length > room) toast.error(`You can attach up to ${MAX_ATTACHMENTS} images per message.`);
      for (const file of images.slice(0, Math.max(0, room))) {
        const key = `att-${++seq.current}`;
        const item: Attachment = { key, name: file.name || "pasted image", preview: URL.createObjectURL(file), status: "uploading" };
        itemsRef.current = [...itemsRef.current, item];
        setItems(itemsRef.current);
        const patch = (p: Partial<Attachment>) => {
          itemsRef.current = itemsRef.current.map((a) => (a.key === key ? { ...a, ...p } : a));
          setItems(itemsRef.current);
        };
        void (async () => {
          try {
            const url = await prepareImage(file);
            const up = await api.uploadImage(url, item.name);
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
    if (gone) URL.revokeObjectURL(gone.preview);
    itemsRef.current = itemsRef.current.filter((a) => a.key !== key);
    setItems(itemsRef.current);
  }, []);

  const clear = useCallback(() => {
    itemsRef.current.forEach((a) => URL.revokeObjectURL(a.preview));
    itemsRef.current = [];
    setItems([]);
  }, []);

  return {
    items,
    ids: items.filter((a) => a.status === "ready" && a.id).map((a) => a.id as string),
    busy: items.some((a) => a.status === "uploading"),
    add, remove, clear,
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

export function AttachButton({ api: att, disabled, reason }: { api: AttachmentsApi; disabled?: boolean; reason?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const full = att.items.length >= MAX_ATTACHMENTS;
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
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
        title={disabled ? reason : full ? `Up to ${MAX_ATTACHMENTS} images` : "Attach images (or paste / drop them)"}
        aria-label="Attach images"
        onClick={() => input.current?.click()}
      >
        <ImagePlus className="h-3.5 w-3.5" aria-hidden /> Image
      </button>
    </>
  );
}

export function AttachmentStrip({ api: att }: { api: AttachmentsApi }) {
  if (!att.items.length) return null;
  return (
    <ul className="flex flex-wrap gap-2 px-3 pt-2" aria-label="Attached images">
      {att.items.map((a) => (
        <li key={a.key} className={cn("group relative h-16 w-16 overflow-hidden rounded-md border", a.status === "error" ? "border-err" : "border-line")}>
          <img src={a.preview} alt={a.name} className={cn("h-full w-full object-cover", a.status !== "ready" && "opacity-50")} />
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

/** Read-only thumbnails of already-uploaded images (chat bubbles, run page). Click opens the full image. */
export function ImageGrid({ ids, className, size = "md" }: { ids: string[]; className?: string; size?: "sm" | "md" }) {
  if (!ids.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)} data-testid="image-grid">
      {ids.map((id) => (
        <a key={id} href={api.uploadUrl(id)} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-md border border-line/60 bg-bg">
          <img src={api.uploadUrl(id)} alt="Attached" loading="lazy" className={cn("w-auto object-cover", size === "sm" ? "h-16" : "max-h-48 max-w-full")} />
        </a>
      ))}
    </div>
  );
}

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { cn } from "../../lib/cn";

interface ToastItem { id: number; kind: "ok" | "err"; text: string }
interface ToastApi { success: (t: string) => void; error: (t: string) => void }
const Ctx = createContext<ToastApi>({ success: () => undefined, error: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (kind: "ok" | "err", text: string) => {
      const id = nextId.current++;
      setItems((l) => [...l.slice(-3), { id, kind, text }]);
      setTimeout(() => dismiss(id), kind === "err" ? 7000 : 3500);
    },
    [dismiss],
  );
  const api = useMemo<ToastApi>(() => ({ success: (t) => push("ok", t), error: (t) => push("err", t) }), [push]);
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.kind === "err" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex animate-slideIn items-start gap-2 rounded-lg border bg-surface px-3 py-2 text-sm shadow-lg",
              t.kind === "ok" ? "border-ok/40" : "border-err/40",
            )}
          >
            {t.kind === "ok" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
            ) : (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-err" />
            )}
            <span className="min-w-0 flex-1 break-words">{t.text}</span>
            <button type="button" aria-label="Dismiss" className="text-muted hover:text-fg" onClick={() => dismiss(t.id)}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);

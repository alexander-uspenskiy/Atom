import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, Bot, Brain, CalendarClock, CalendarX, Check, CircleHelp, Pencil, X, type LucideIcon,
} from "lucide-react";
import { api } from "../api/client";
import { invalidate } from "../api/hooks";
import type { PendingAction } from "../api/types";
import { Badge, StatusBadge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import { JsonBlock } from "./ui/CodeBlock";
import { useToast } from "./ui/Toast";
import { errMsg, fmtRelative, prettyJSON } from "../lib/format";
import { cn } from "../lib/cn";

export const kindMeta: Record<string, { icon: LucideIcon; label: string }> = {
  create_schedule: { icon: CalendarClock, label: "Create schedule" },
  update_schedule: { icon: CalendarClock, label: "Update schedule" },
  delete_schedule: { icon: CalendarX, label: "Delete schedule" },
  create_agent: { icon: Bot, label: "Create agent" },
  create_skill: { icon: BookOpen, label: "Create skill" },
  save_memory: { icon: Brain, label: "Save memory" },
  update_memory: { icon: Brain, label: "Update memory" },
};

export function ApprovalCard({ action: initial, compact }: { action: PendingAction; compact?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [decided, setDecided] = useState<PendingAction | null>(null);
  const action = decided ?? initial;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(() => prettyJSON(initial.payload));
  const [parseErr, setParseErr] = useState<string | null>(null);
  const meta = kindMeta[action.kind] ?? { icon: CircleHelp, label: action.kind };
  const Icon = meta.icon;
  const pending = action.status === "pending";

  const done = (a: PendingAction, verb: string) => {
    setDecided(a);
    setEditing(false);
    invalidate(qc, "actions", "status", "schedules", "agents", "skills", "memories");
    if (a.status === "failed") toast.error(`${meta.label} failed${a.result ? `: ${prettyJSON(a.result)}` : ""}`);
    else toast.success(`${verb}: ${action.summary ?? meta.label}`);
  };
  const approve = useMutation({
    mutationFn: () => {
      if (!editing) return api.approveAction(action.id);
      let payload: unknown;
      try {
        payload = JSON.parse(text);
      } catch (e) {
        throw new Error(`Payload is not valid JSON: ${errMsg(e)}`);
      }
      return api.approveAction(action.id, payload);
    },
    onSuccess: (a) => done(a, "Approved"),
    onError: (e) => {
      setParseErr(errMsg(e));
      toast.error(errMsg(e));
    },
  });
  const reject = useMutation({
    mutationFn: () => api.rejectAction(action.id),
    onSuccess: (a) => done(a, "Rejected"),
    onError: (e) => toast.error(errMsg(e)),
  });
  const busy = approve.isPending || reject.isPending;

  return (
    <Card className={cn("overflow-hidden", pending && "border-warn/50")}>
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md", pending ? "bg-warn/10 text-warn" : "bg-surface2 text-muted")}>
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">{meta.label}</span>
            <StatusBadge status={action.status} />
            {action.created_by && <Badge>{action.created_by}</Badge>}
            {action.created_at ? <span className="text-xs text-muted">{fmtRelative(action.created_at)}</span> : null}
          </div>
          <p className="mt-0.5 break-words text-sm font-medium">{action.summary || "(no summary)"}</p>
        </div>
      </div>

      {action.payload !== undefined && action.payload !== null && (
        <div className="border-t border-line px-3 py-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium text-muted">Payload</span>
            {pending && (
              <button
                type="button"
                className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                onClick={() => {
                  setEditing((v) => !v);
                  setParseErr(null);
                }}
              >
                <Pencil className="h-3 w-3" /> {editing ? "Discard edits" : "Edit"}
              </button>
            )}
          </div>
          {editing ? (
            <>
              <textarea
                aria-label="Edit payload JSON"
                spellCheck={false}
                className="input mono h-48 resize-y leading-relaxed"
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setParseErr(null);
                }}
              />
              {parseErr && <p className="mt-1 text-xs text-err">{parseErr}</p>}
            </>
          ) : (
            <JsonBlock value={action.payload} maxHeight={compact ? "10rem" : "16rem"} className="!my-0" />
          )}
        </div>
      )}

      {action.status === "failed" && action.result ? (
        <div className="border-t border-line px-3 py-2 text-xs text-err">{prettyJSON(action.result)}</div>
      ) : null}

      {pending && (
        <div className="flex justify-end gap-2 border-t border-line bg-surface2/50 px-3 py-2">
          <Button size="sm" variant="danger" icon={<X className="h-3.5 w-3.5" />} loading={reject.isPending} disabled={busy} onClick={() => reject.mutate()}>
            Reject
          </Button>
          <Button size="sm" variant="primary" icon={<Check className="h-3.5 w-3.5" />} loading={approve.isPending} disabled={busy} onClick={() => approve.mutate()}>
            {editing ? "Approve edited" : "Approve"}
          </Button>
        </div>
      )}
    </Card>
  );
}

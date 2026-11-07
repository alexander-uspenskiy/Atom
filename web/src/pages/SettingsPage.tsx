import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw, Save, Undo2 } from "lucide-react";
import { api } from "../api/client";
import { qk, useSettings } from "../api/hooks";
import type { SettingField, SettingValue } from "../api/types";
import { Page } from "../components/Page";
import { Button, IconButton } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";
import { Select } from "../components/ui/Select";
import { ErrorState, Loading } from "../components/ui/Spinner";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { errMsg } from "../lib/format";
import { cn } from "../lib/cn";

type Values = Record<string, SettingValue>;
const same = (a: SettingValue | undefined, b: SettingValue | undefined) => (a ?? null) === (b ?? null);

function Control({ f, value, onChange }: { f: SettingField; value: SettingValue | undefined; onChange: (v: SettingValue) => void }) {
  const id = `set-${f.key}`;
  switch (f.type) {
    case "boolean":
      return <Switch id={id} checked={value === true} onChange={onChange} label={f.label} />;
    case "select":
      return <Select id={id} className="w-56" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} options={f.options ?? []} />;
    case "slider": {
      const num = typeof value === "number" ? value : Number(value ?? f.min ?? 0);
      return (
        <div className="flex w-72 items-center gap-3">
          <input id={id} type="range" className="h-1.5 flex-1 accent-[rgb(var(--accent))]" min={f.min} max={f.max} step={f.step} value={Number.isFinite(num) ? num : 0} onChange={(e) => onChange(Number(e.target.value))} aria-valuetext={String(num)} />
          <output htmlFor={id} className="w-14 text-right font-mono text-xs tabular-nums">{Number.isFinite(num) ? num : "–"}</output>
        </div>
      );
    }
    case "number":
      return (
        <input id={id} type="number" className="input w-32" min={f.min} max={f.max} step={f.step} value={value === null || value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
      );
    default:
      return <input id={id} type="text" className="input w-full max-w-md" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} spellCheck={false} />;
  }
}

export default function SettingsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useSettings();
  const [draft, setDraft] = useState<Values>({});
  const server = q.data?.values;
  useEffect(() => {
    if (server) setDraft(server);
  }, [server]);

  const defaults = q.data?.defaults ?? {};
  const groups = useMemo(() => {
    const m = new Map<string, SettingField[]>();
    for (const f of q.data?.schema ?? []) {
      const g = f.group || "General";
      m.set(g, [...(m.get(g) ?? []), f]);
    }
    return [...m.entries()];
  }, [q.data?.schema]);

  const dirtyKeys = (q.data?.schema ?? []).map((f) => f.key).filter((k) => !same(draft[k], server?.[k]));
  const save = useMutation({
    mutationFn: () => api.saveSettings(Object.fromEntries(dirtyKeys.map((k) => [k, draft[k] ?? null]))),
    onSuccess: (res) => {
      qc.setQueryData(qk.settings, res);
      void qc.invalidateQueries({ queryKey: qk.status });
      setDraft(res.values);
      toast.success(`Saved ${dirtyKeys.length} setting${dirtyKeys.length === 1 ? "" : "s"}`);
    },
    onError: (e) => toast.error(`Could not save: ${errMsg(e)}`),
  });

  return (
    <Page
      title="Settings"
      subtitle={dirtyKeys.length ? `${dirtyKeys.length} unsaved change${dirtyKeys.length === 1 ? "" : "s"}` : "Model, agent and system configuration"}
      actions={
        <>
          <Button icon={<Undo2 className="h-4 w-4" />} disabled={!dirtyKeys.length || save.isPending} onClick={() => server && setDraft(server)}>Discard</Button>
          <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={save.isPending} disabled={!dirtyKeys.length} onClick={() => save.mutate()}>Save changes</Button>
        </>
      }
    >
      {q.isLoading && <Loading />}
      {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      <div className="mx-auto max-w-3xl space-y-4">
        {groups.map(([group, fields]) => (
          <Card key={group}>
            <CardHeader title={group} />
            <div className="divide-y divide-line">
              {fields.map((f) => {
                const v = draft[f.key];
                const dirty = !same(v, server?.[f.key]);
                const isDefault = !(f.key in defaults) || same(v, defaults[f.key]);
                const warnThinking = /thinking/.test(f.key) && (v === "on" || v === true);
                return (
                  <div key={f.key} className={cn("grid gap-x-6 gap-y-1 px-3 py-2.5 md:grid-cols-[minmax(0,1fr)_auto]", dirty && "bg-accent/5")} data-dirty={dirty}>
                    <div className="min-w-0">
                      <label htmlFor={`set-${f.key}`} className="flex items-center gap-1.5 text-sm font-medium">
                        {f.label}
                        {dirty && <span className="h-1.5 w-1.5 rounded-full bg-accent" title="Unsaved" aria-label="unsaved change" />}
                      </label>
                      <div className="font-mono text-[11px] text-muted">{f.key}</div>
                      {f.help && (
                        <p className={cn("mt-1 flex items-start gap-1 text-xs", warnThinking ? "rounded bg-warn/10 px-1.5 py-1 font-medium text-warn" : "text-muted")}>
                          {warnThinking && <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
                          <span>{f.help}</span>
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 md:justify-end">
                      <Control f={f} value={v} onChange={(nv) => setDraft((d) => ({ ...d, [f.key]: nv }))} />
                      <IconButton label={isDefault ? "Already at default" : `Reset to default (${String(defaults[f.key])})`} disabled={isDefault} onClick={() => setDraft((d) => ({ ...d, [f.key]: defaults[f.key] ?? null }))}>
                        <RotateCcw className="h-3.5 w-3.5" />
                      </IconButton>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        ))}
      </div>
    </Page>
  );
}

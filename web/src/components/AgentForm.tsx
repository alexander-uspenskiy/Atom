import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { invalidate, useModels, useSkills, useTools } from "../api/hooks";
import type { Agent, AgentInput, Effort, Thinking } from "../api/types";
import { errMsg } from "../lib/format";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { ChipsInput, Field, MultiSelect } from "./ui/Fields";
import { FolderPicker } from "./ui/FolderPicker";
import { Select } from "./ui/Select";
import { Switch } from "./ui/Switch";
import { useToast } from "./ui/Toast";

export const THINKING_OPTS = ["inherit", "off", "auto", "on"] as const;
export const EFFORT_OPTS = ["inherit", "low", "medium", "xhigh"] as const;

export function OptionalNumber({
  value, onChange, min, max, step, label, inheritLabel = "inherit",
}: { value: number | null; onChange: (v: number | null) => void; min?: number; max?: number; step?: number; label: string; inheritLabel?: string }) {
  return (
    <div className="flex items-center gap-2">
      <input
        aria-label={label}
        type="number"
        className="input w-28"
        min={min}
        max={max}
        step={step}
        disabled={value === null}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
      />
      <label className="inline-flex items-center gap-1.5 text-xs text-muted">
        <input
          type="checkbox"
          className="accent-[rgb(var(--accent))]"
          checked={value === null}
          onChange={(e) => onChange(e.target.checked ? null : (min ?? 1))}
        />
        {inheritLabel}
      </label>
    </div>
  );
}

const blank: AgentInput = {
  name: "", description: "", instructions: "", start_url: null, allowed_domains: [], allow_private: false,
  tools: null, skills: [], memory_scope: "agent", thinking: "inherit", effort: "inherit", max_steps: null, temperature: null, profile: null, workdir: null, model: null,
};

export function AgentForm({ open, onClose, agent }: { open: boolean; onClose: () => void; agent?: Agent | null }) {
  const qc = useQueryClient();
  const toast = useToast();
  const models = useModels();
  const tools = useTools();
  const skills = useSkills();
  const [f, setF] = useState<AgentInput>(blank);
  const set = <K extends keyof AgentInput>(k: K, v: AgentInput[K]) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    if (!open) return;
    if (agent) {
      const { id: _i, created_at: _c, updated_at: _u, is_default: _d, ...rest } = agent;
      void [_i, _c, _u, _d];
      setF({ ...blank, ...rest, allowed_domains: rest.allowed_domains ?? [], skills: rest.skills ?? [] });
    } else setF(blank);
  }, [open, agent]);

  const save = useMutation({
    mutationFn: (body: AgentInput) => (agent ? api.updateAgent(agent.id, body) : api.createAgent(body)),
    onSuccess: () => {
      invalidate(qc, "agents");
      toast.success(agent ? "Agent updated" : "Agent created");
      onClose();
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const allTools = f.tools === null || f.tools === undefined;
  const submit = () =>
    save.mutate({
      ...f,
      name: f.name.trim(),
      start_url: f.start_url?.trim() || null,
      profile: f.profile?.trim() || null,
      workdir: f.workdir?.trim() || null,
      description: f.description ?? "",
      instructions: f.instructions ?? "",
    });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      wide
      title={agent ? `Edit agent: ${agent.name}` : "New agent"}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} disabled={!f.name.trim()} onClick={submit}>{agent ? "Save" : "Create"}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="ag-name"><input id="ag-name" className="input" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="News watcher" /></Field>
          <Field label="Start URL" htmlFor="ag-url"><input id="ag-url" className="input" value={f.start_url ?? ""} onChange={(e) => set("start_url", e.target.value)} placeholder="https://…" /></Field>
        </div>
        <Field label="Description" htmlFor="ag-desc"><input id="ag-desc" className="input" value={f.description ?? ""} onChange={(e) => set("description", e.target.value)} /></Field>
        <Field label="Extra instructions (appended to the system prompt)" htmlFor="ag-instr">
          <textarea id="ag-instr" className="input h-24 resize-y" value={f.instructions ?? ""} onChange={(e) => set("instructions", e.target.value)} />
        </Field>

        <Field label="Allowed domains" hint="Empty = unrestricted. Press Enter or comma to add.">
          <ChipsInput value={f.allowed_domains ?? []} onChange={(v) => set("allowed_domains", v)} placeholder="example.com" label="Allowed domains" />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={!!f.allow_private} onChange={(v) => set("allow_private", v)} label="Allow private network addresses" /> Allow private / local network addresses
        </label>

        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Tools">
            <label className="mb-1.5 flex items-center gap-2 text-sm">
              <Switch checked={allTools} onChange={(v) => set("tools", v ? null : (tools.data ?? []).map((t) => t.name))} label="All tools" /> All tools
            </label>
            {!allTools && (
              <MultiSelect
                options={(tools.data ?? []).map((t) => ({ value: t.name, label: t.name, hint: `${t.side_effect ? "⚠ side effects · " : ""}${t.description ?? ""}` }))}
                value={f.tools ?? []}
                onChange={(v) => set("tools", v)}
                emptyText={tools.isLoading ? "Loading tools…" : "No tools available"}
              />
            )}
          </Field>
          <Field label="Skills">
            <MultiSelect
              options={(skills.data ?? []).map((s) => ({ value: s.name, label: s.name, hint: s.description }))}
              value={f.skills ?? []}
              onChange={(v) => set("skills", v)}
              emptyText={skills.isLoading ? "Loading skills…" : "No skills yet — create some on the Skills page"}
            />
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Memory scope" htmlFor="ag-mem">
            <Select id="ag-mem" value={f.memory_scope ?? "agent"} onChange={(e) => set("memory_scope", e.target.value as AgentInput["memory_scope"])} options={["none", "global", "agent"]} />
          </Field>
          <Field label="Thinking" htmlFor="ag-think" hint="“on” breaks the prompt cache.">
            <Select id="ag-think" value={f.thinking ?? "inherit"} onChange={(e) => set("thinking", e.target.value as Thinking)} options={[...THINKING_OPTS]} />
          </Field>
          <Field label="Effort" htmlFor="ag-effort">
            <Select id="ag-effort" value={f.effort ?? "inherit"} onChange={(e) => set("effort", e.target.value as Effort)} options={[...EFFORT_OPTS]} />
          </Field>
          <Field label="Model" htmlFor="ag-model" hint="Which model runs this agent. Default follows the model chosen in the sidebar.">
            <Select id="ag-model" value={f.model ?? ""} onChange={(e) => set("model", e.target.value || null)}
              options={[{ value: "", label: "Default (active model)" }, ...(models.data?.models ?? []).map((m) => ({ value: m.id, label: `${m.label}${m.installed ? "" : " (not downloaded)"}` }))]} />
          </Field>
          <Field label="Max steps">
            <OptionalNumber label="Max steps" min={1} max={500} value={f.max_steps ?? null} onChange={(v) => set("max_steps", v)} />
          </Field>
          <Field label="Temperature">
            <OptionalNumber label="Temperature" min={0} max={2} step={0.05} value={f.temperature ?? null} onChange={(v) => set("temperature", v)} />
          </Field>
          <Field label="Working folder" htmlFor="ag-wd" hint="Where this agent's terminal commands start. Empty = the global folder in Settings → Terminal. Needs the terminal tool selected.">
            <FolderPicker id="ag-wd" value={f.workdir ?? ""} onChange={(v) => set("workdir", v)} />
          </Field>
          <Field label="Browser profile" htmlFor="ag-prof" hint="Optional persistent profile name">
            <input id="ag-prof" className="input" value={f.profile ?? ""} onChange={(e) => set("profile", e.target.value)} />
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

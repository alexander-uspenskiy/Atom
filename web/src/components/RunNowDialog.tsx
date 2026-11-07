import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { invalidate } from "../api/hooks";
import type { Agent, Effort, RunOverrides, Thinking } from "../api/types";
import { errMsg } from "../lib/format";
import { EFFORT_OPTS, OptionalNumber, THINKING_OPTS } from "./AgentForm";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { Field } from "./ui/Fields";
import { Select } from "./ui/Select";
import { useToast } from "./ui/Toast";

export function RunNowDialog({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [task, setTask] = useState("");
  const [url, setUrl] = useState("");
  const [thinking, setThinking] = useState<Thinking>("inherit");
  const [effort, setEffort] = useState<Effort>("inherit");
  const [maxSteps, setMaxSteps] = useState<number | null>(null);

  useEffect(() => {
    if (!agent) return;
    setTask("");
    setUrl(agent.start_url ?? "");
    setThinking("inherit");
    setEffort("inherit");
    setMaxSteps(null);
  }, [agent]);

  const run = useMutation({
    mutationFn: () => {
      const overrides: RunOverrides = {};
      if (thinking !== "inherit") overrides.thinking = thinking;
      if (effort !== "inherit") overrides.effort = effort;
      if (maxSteps !== null) overrides.max_steps = maxSteps;
      return api.runAgent((agent as Agent).id, { task: task.trim(), start_url: url.trim() || null, overrides });
    },
    onSuccess: (r) => {
      invalidate(qc, "runs", "status");
      onClose();
      nav(`/runs/${encodeURIComponent(r.run_id)}`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  return (
    <Dialog
      open={agent !== null}
      onClose={onClose}
      title={`Run “${agent?.name ?? ""}” now`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={run.isPending} disabled={!task.trim()} onClick={() => run.mutate()}>Start run</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Task" htmlFor="rn-task">
          <textarea id="rn-task" data-autofocus className="input h-28 resize-y" value={task} onChange={(e) => setTask(e.target.value)} placeholder="What should the agent do?" />
        </Field>
        <Field label="Start URL (optional)" htmlFor="rn-url"><input id="rn-url" className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Thinking" htmlFor="rn-think"><Select id="rn-think" value={thinking} onChange={(e) => setThinking(e.target.value as Thinking)} options={[...THINKING_OPTS]} /></Field>
          <Field label="Effort" htmlFor="rn-eff"><Select id="rn-eff" value={effort} onChange={(e) => setEffort(e.target.value as Effort)} options={[...EFFORT_OPTS]} /></Field>
          <Field label="Max steps"><OptionalNumber label="Max steps" min={1} max={500} value={maxSteps} onChange={setMaxSteps} /></Field>
        </div>
      </div>
    </Dialog>
  );
}

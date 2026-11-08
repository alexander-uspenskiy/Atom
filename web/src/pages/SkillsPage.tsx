import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Plus, Save, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { invalidate, useProjects, useSkills } from "../api/hooks";
import type { Skill } from "../api/types";
import { Page } from "../components/Page";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/Dialog";
import { Field } from "../components/ui/Fields";
import { Markdown } from "../components/ui/Markdown";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { errMsg, slugOk } from "../lib/format";
import { cn } from "../lib/cn";

interface Draft { name: string; description: string; when_to_use: string; body: string; enabled: boolean }
const blank: Draft = { name: "", description: "", when_to_use: "", body: "# Steps\n1. ", enabled: true };
const fromSkill = (s: Skill): Draft => ({ name: s.name, description: s.description ?? "", when_to_use: s.when_to_use ?? "", body: s.body ?? "", enabled: s.enabled !== false });

export default function SkillsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [projectId, setProjectId] = useState<string>("");     // "" = user-level skills only
  const [newScope, setNewScope] = useState<"user" | "project">("user");
  const projects = (useProjects().data ?? []).filter((p) => !!p.folder);
  const q = useSkills(projectId || null);
  const [sel, setSel] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(blank);
  const [saved, setSaved] = useState<Draft>(blank);
  const [del, setDel] = useState(false);

  const skills = q.data ?? [];
  const current = skills.find((s) => s.name === sel);
  useEffect(() => {
    if (sel === "new") {
      setDraft(blank);
      setSaved(blank);
    } else if (current) {
      const d = fromSkill(current);
      setDraft(d);
      setSaved(d);
    }
    // only re-seed when the selection changes or the stored skill itself changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, current?.updated_at, current?.name]);
  useEffect(() => {
    if (sel === null && skills.length) setSel(skills[0].name);
  }, [sel, skills]);

  const isNew = sel === "new";
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const nameErr = useMemo(() => (isNew && draft.name && !slugOk(draft.name) ? "Use lowercase letters, digits and single dashes (e.g. summarize-news)" : null), [isNew, draft.name]);
  const duplicate = isNew && skills.some((s) => s.name === draft.name);

  const save = useMutation({
    mutationFn: () => {
      const body: Skill = { ...draft };
      return isNew ? api.createSkill({ ...body, scope: projectId ? newScope : "user" }, projectId || null) : api.updateSkill(draft.name, body, projectId || null);
    },
    onSuccess: (s) => {
      invalidate(qc, "skills");
      toast.success(isNew ? "Skill created" : "Skill saved");
      const d = fromSkill({ ...draft, ...s });
      setSaved(d);
      setDraft(d);
      setSel(draft.name);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteSkill(draft.name, projectId || null),
    onSuccess: () => {
      invalidate(qc, "skills");
      toast.success("Skill deleted");
      setDel(false);
      setSel(null);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const toggle = useMutation({
    mutationFn: (v: { s: Skill; enabled: boolean }) => api.updateSkill(v.s.name, { ...v.s, enabled: v.enabled }, projectId || null),
    onSuccess: () => invalidate(qc, "skills"),
    onError: (e) => toast.error(errMsg(e)),
  });

  const canSave = !!draft.name && !nameErr && !duplicate && !!draft.body.trim() && (isNew || dirty);

  return (
    <Page title="Skills" subtitle="Reusable procedures stored as SKILL.md files: yours in ~/.atom/skills, a project's in its .atom/skills or .agents/skills" actions={<><select className="input w-48" aria-label="Project" value={projectId} onChange={(e) => { setProjectId(e.target.value); setSel(null); setNewScope("user"); }}><option value="">User skills only</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select><Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setSel("new")}>New skill</Button></>} fill>
      <div className="flex h-full">
        <aside className="w-60 shrink-0 overflow-y-auto border-r border-line bg-surface p-1.5" aria-label="Skills">
          {q.isLoading && <Loading />}
          {q.error && !q.data && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
          {q.data && skills.length === 0 && sel !== "new" && <p className="px-2 py-6 text-center text-xs text-muted">No skills yet.</p>}
          {isNew && <div className="rounded-md bg-accent/10 px-2 py-1.5 text-sm font-medium text-accent">New skill…</div>}
          {skills.map((s) => (
            <div key={s.name} className={cn("flex items-center gap-1.5 rounded-md pr-1.5", s.name === sel ? "bg-accent/10" : "hover:bg-surface2")}>
              <button type="button" className="min-w-0 flex-1 px-2 py-1.5 text-left" aria-current={s.name === sel} onClick={() => setSel(s.name)}>
                <div className={cn("truncate font-mono text-xs font-semibold", s.name === sel && "text-accent", s.enabled === false && "opacity-60")}>{s.name}</div>
                <div className="truncate text-xs text-muted">{s.scope === "project" ? "project · " : ""}{s.description || "—"}</div>
              </button>
              <Switch checked={s.enabled !== false} label={`Enable ${s.name}`} onChange={(enabled) => toggle.mutate({ s, enabled })} />
            </div>
          ))}
        </aside>

        <section className="min-w-0 flex-1 overflow-y-auto p-4">
          {sel === null || (!isNew && !current) ? (
            !q.isLoading && <Card><EmptyState icon={BookOpen} title="Select or create a skill" hint="Skills are markdown procedures that agents can load when relevant." /></Card>
          ) : (
            <div className="mx-auto max-w-6xl space-y-3">
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Name (slug)" htmlFor="sk-name" error={nameErr ?? (duplicate ? "A skill with this name already exists" : null)}>
                  <input id="sk-name" className="input font-mono" value={draft.name} readOnly={!isNew} disabled={!isNew} placeholder="summarize-news" spellCheck={false} onChange={(e) => setDraft({ ...draft, name: e.target.value.toLowerCase() })} />
                </Field>
                <div className="flex items-end gap-3 pb-1">
                  <label className="flex items-center gap-2 text-sm"><Switch checked={draft.enabled} onChange={(enabled) => setDraft({ ...draft, enabled })} label="Enabled" /> Enabled</label>
                  {isNew && projectId && (
                    <select className="input w-40" aria-label="Save to" value={newScope} onChange={(e) => setNewScope(e.target.value as "user" | "project")}>
                      <option value="user">User skill</option><option value="project">Project skill</option>
                    </select>
                  )}
                  {current?.scope === "project" && <Badge tone="accent">project</Badge>}
                  {current?.created_by === "assistant" && <Badge tone="accent">created by assistant</Badge>}
                </div>
                <Field label="Description" htmlFor="sk-desc"><input id="sk-desc" className="input" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></Field>
                <Field label="When to use" htmlFor="sk-when"><input id="sk-when" className="input" value={draft.when_to_use} onChange={(e) => setDraft({ ...draft, when_to_use: e.target.value })} /></Field>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <Field label="Body (markdown)" htmlFor="sk-body">
                  <textarea id="sk-body" className="input mono h-[26rem] resize-y leading-relaxed" spellCheck={false} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
                </Field>
                <div>
                  <span className="label">Preview</span>
                  <Card className="h-[26rem] overflow-y-auto px-3 py-2" aria-label="Markdown preview">
                    {draft.body.trim() ? <Markdown text={draft.body} /> : <p className="text-sm text-muted">Nothing to preview.</p>}
                  </Card>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div>{!isNew && <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setDel(true)}>Delete</Button>}</div>
                <div className="flex items-center gap-2">
                  {dirty && <span className="text-xs text-warn">Unsaved changes</span>}
                  <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={save.isPending} disabled={!canSave} onClick={() => save.mutate()}>{isNew ? "Create" : "Save"}</Button>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
      <ConfirmDialog open={del} onClose={() => setDel(false)} onConfirm={() => remove.mutate()} loading={remove.isPending} title="Delete skill?" message={<>The skill “{draft.name}” and its SKILL.md will be removed.</>} />
    </Page>
  );
}

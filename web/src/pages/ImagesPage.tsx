import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { Copy, Dices, FolderOpen, Image as ImageIcon, Loader2, RotateCcw, Send, SlidersHorizontal, Trash2 } from "lucide-react";
import { api, localFileUrl } from "../api/client";
import { useImageModels } from "../api/hooks";
import type { ImageLabBody, ImageLabResult, ImageModel } from "../api/types";
import { Page } from "../components/Page";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Field } from "../components/ui/Fields";
import { Select } from "../components/ui/Select";
import { useToast } from "../components/ui/Toast";
import { cn } from "../lib/cn";
import { errMsg } from "../lib/format";
import { lsGet, lsSet } from "../lib/storage";

const MODEL_KEY = "atom-images-model";
const SETTINGS_KEY = "atom-images-settings";
const HISTORY_KEY = "atom-images-history";
const HISTORY_MAX = 30;

/** Per-model form values. An empty string means "use the model's default" (shown as the placeholder). */
interface Knobs { size: string; steps: string; cfg: string; sampler: string; seed: string; negative: string }
const EMPTY_KNOBS: Knobs = { size: "1024x1024", steps: "", cfg: "", sampler: "", seed: "", negative: "" };

interface Item {
  id: string; model: string; prompt: string; body: ImageLabBody; at: number;
  status: "pending" | "done" | "error"; result?: ImageLabResult; error?: string;
}

const EXAMPLES: Record<ImageModel["style"], string[]> = {
  tags: [
    "1girl, solo, adult, long silver hair, red eyes, black coat, standing, rain, city street, night, neon lights, cowboy shot",
    "scenery, no humans, lighthouse on a cliff, sunset, orange sky, ocean waves, clouds, detailed",
  ],
  natural: [
    "Photo of an adult woman in her late twenties on a balcony at golden hour, linen shirt, 85mm, shallow depth of field",
    "A red fox standing in fresh snow at dawn, soft light, detailed fur, telephoto photo",
  ],
};

function loadJSON<T>(key: string, fallback: T): T {
  try {
    const v = JSON.parse(lsGet(key) ?? "null") as T | null;
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

const num = (s: string): number | null => {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) ? n : null;
};

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="tabular-nums">{Math.max(0, Math.round((now - since) / 1000))}s</span>;
}

function UserBubble({ item }: { item: Item }) {
  const b = item.body;
  const extras = [b.size, b.steps ? `${b.steps} steps` : "", b.cfg ? `cfg ${b.cfg}` : "", b.sampler ?? "", b.seed != null ? `seed ${b.seed}` : ""].filter(Boolean);
  return (
    <div className="flex justify-end" data-testid="image-prompt">
      <div className="flex max-w-[85%] flex-col items-end gap-1">
        <div className="whitespace-pre-wrap break-words rounded-lg rounded-tr-sm bg-accent px-3 py-2 text-sm text-accent-fg">{item.prompt}</div>
        {b.negative_prompt && <div className="max-w-full truncate text-xs text-muted" title={b.negative_prompt}>negative: {b.negative_prompt}</div>}
        <div className="text-xs text-muted">{item.model}{extras.length > 0 && ` · ${extras.join(" · ")}`}</div>
      </div>
    </div>
  );
}

function ResultBubble({ item, onReuse, onSeed }: { item: Item; onReuse: (i: Item) => void; onSeed: (seed: number) => void }) {
  const toast = useToast();
  const r = item.result;
  return (
    <div className="flex gap-2.5" data-testid="image-result">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent" aria-hidden>
        <ImageIcon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {item.status === "pending" && (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Generating with {item.model}… <Elapsed since={item.at} />
            <span className="text-xs">(the first image after switching models also loads the checkpoint)</span>
          </p>
        )}
        {item.status === "error" && (
          <div role="alert" className="rounded-md border border-err/40 bg-err/5 px-3 py-2 text-sm">
            <div className="font-medium text-err">Generation failed</div>
            <div className="mt-0.5 break-words text-xs text-muted">{item.error}</div>
          </div>
        )}
        {r && (
          <>
            <a href={localFileUrl(r.path)} target="_blank" rel="noreferrer noopener" className="inline-block" title="Open full size">
              <img
                src={localFileUrl(r.path)}
                alt={item.prompt}
                loading="lazy"
                className="max-h-[28rem] max-w-full rounded-lg border border-line bg-surface2"
              />
            </a>
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
              <Badge tone="accent">{r.model}</Badge>
              <span>{r.width}×{r.height}</span>
              <span>· seed {r.seed}</span>
              <span>· {r.seconds}s</span>
            </div>
            <div className="min-w-0">
              <a
                href={localFileUrl(r.path)}
                target="_blank"
                rel="noreferrer noopener"
                className="break-all font-mono text-xs text-accent underline underline-offset-2"
                data-testid="image-path"
              >
                {r.path}
              </a>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Button
                size="sm"
                icon={<Copy className="h-3.5 w-3.5" />}
                onClick={() => void navigator.clipboard.writeText(r.path).then(() => toast.success("Path copied"), () => toast.error("Could not copy"))}
              >
                Copy path
              </Button>
              <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => onReuse(item)}>Reuse settings</Button>
              <Button size="sm" onClick={() => onSeed(r.seed)} title="Keep this composition and change the prompt">Use this seed</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function ImagesPage() {
  const q = useImageModels();
  const models = q.data?.models ?? [];
  const [modelId, setModelId] = useState(() => lsGet(MODEL_KEY) ?? "");
  const [knobsByModel, setKnobsByModel] = useState<Record<string, Knobs>>(() => loadJSON(SETTINGS_KEY, {}));
  const [prompt, setPrompt] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [items, setItems] = useState<Item[]>(() => loadJSON<Item[]>(HISTORY_KEY, []).filter((i) => i.status === "done"));
  const ta = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  // Default to the first model that is actually installed once the list arrives.
  const model: ImageModel | undefined = useMemo(
    () => models.find((m) => m.id === modelId) ?? models.find((m) => m.up && m.present) ?? models[0],
    [models, modelId],
  );
  const knobs = (model && knobsByModel[model.id]) || EMPTY_KNOBS;
  const setKnobs = (patch: Partial<Knobs>) => {
    if (!model) return;
    setKnobsByModel((all) => {
      const next = { ...all, [model.id]: { ...(all[model.id] ?? EMPTY_KNOBS), ...patch } };
      lsSet(SETTINGS_KEY, JSON.stringify(next));
      return next;
    });
  };
  const pickModel = (id: string) => {
    setModelId(id);
    lsSet(MODEL_KEY, id);
  };

  const busy = items.some((i) => i.status === "pending");
  const ready = !!model && model.up && model.present;
  const d = model?.defaults;

  useEffect(() => {
    lsSet(HISTORY_KEY, JSON.stringify(items.filter((i) => i.status === "done").slice(-HISTORY_MAX)));
    end.current?.scrollIntoView({ block: "end" });
  }, [items]);
  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    if (!prompt) {                       // empty: one natural row (a long placeholder must not stretch it)
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [prompt]);

  const send = useCallback(async () => {
    const text = prompt.trim();
    if (!text || !model || busy || !ready) return;
    const body: ImageLabBody = {
      model: model.id, prompt: text, size: knobs.size || "1024x1024",
      seed: num(knobs.seed), steps: num(knobs.steps),
      cfg: model.supports.cfg ? num(knobs.cfg) : null,
      sampler: model.supports.sampler && knobs.sampler ? knobs.sampler : null,
      negative_prompt: model.supports.negative && knobs.negative.trim() ? knobs.negative.trim() : null,
    };
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setItems((l) => [...l, { id, model: model.id, prompt: text, body, at: Date.now(), status: "pending" }]);
    setPrompt("");
    try {
      const result = await api.imagelabGenerate(body);
      setItems((l) => l.map((i) => (i.id === id ? { ...i, status: "done", result } : i)));
      void q.refetch();
    } catch (e) {
      setItems((l) => l.map((i) => (i.id === id ? { ...i, status: "error", error: errMsg(e) } : i)));
    }
  }, [prompt, model, busy, ready, knobs, q]);

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  const reuse = (i: Item) => {
    const m = models.find((x) => x.id === i.model);
    if (m) pickModel(m.id);
    setPrompt(i.prompt);
    setKnobsByModel((all) => {
      const b = i.body;
      const next = {
        ...all,
        [i.model]: {
          size: b.size, steps: b.steps ? String(b.steps) : "", cfg: b.cfg ? String(b.cfg) : "", sampler: b.sampler ?? "",
          seed: b.seed != null ? String(b.seed) : "", negative: b.negative_prompt ?? "",
        },
      };
      lsSet(SETTINGS_KEY, JSON.stringify(next));
      return next;
    });
    ta.current?.focus();
  };

  const status = !model ? null : !model.up
    ? { tone: "err" as const, text: `${model.backend === "sdxl" ? "SDXL" : "Z-Image"} service is not running` }
    : !model.present
      ? { tone: "warn" as const, text: "checkpoint not installed" }
      : model.loaded
        ? { tone: "ok" as const, text: "loaded" }
        : { tone: "neutral" as const, text: "loads on first use" };
  const examples = EXAMPLES[model?.style ?? "natural"];

  return (
    <Page
      title="Images"
      subtitle="Talk to the image models directly — no assistant in between"
      fill
      actions={
        <>
          <span className="inline-flex max-w-[24rem] items-center gap-1.5 text-xs text-muted" title="Finished images are saved here (Settings → Image generation)">
            <FolderOpen className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="truncate font-mono">{q.data?.output_dir ?? "…"}</span>
          </span>
          <Link to="/settings" className="text-xs text-accent underline underline-offset-2">Change</Link>
          {items.length > 0 && (
            <Button size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} disabled={busy} onClick={() => setItems([])} title="Clears this list only; image files stay on disk">
              Clear
            </Button>
          )}
        </>
      }
    >
      <div className="flex h-full min-h-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mx-auto max-w-3xl space-y-4">
            {items.length === 0 && (
              <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center">
                <ImageIcon className="mx-auto h-6 w-6 text-muted" aria-hidden />
                <p className="mt-2 text-sm font-medium">Pick a model and type a prompt</p>
                <p className="mx-auto mt-1 max-w-md text-xs text-muted">
                  {model?.style === "tags"
                    ? "This model reads comma-separated tags, not sentences. Quality tags are added for you."
                    : "Plain descriptive English works best: subject, setting, light, camera."}
                  {" "}Results are saved to the output folder and shown here with a clickable path.
                </p>
                <div className="mt-3 flex flex-col items-center gap-1.5">
                  {examples.map((ex) => (
                    <button key={ex} type="button" onClick={() => { setPrompt(ex); ta.current?.focus(); }} className="max-w-xl truncate rounded-md border border-line px-2.5 py-1 text-left text-xs text-muted hover:bg-surface2 hover:text-fg">
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {items.map((i) => (
              <div key={i.id} className="space-y-3">
                <UserBubble item={i} />
                <ResultBubble item={i} onReuse={reuse} onSeed={(seed) => { setKnobs({ seed: String(seed) }); setShowSettings(true); }} />
              </div>
            ))}
            <div ref={end} />
          </div>
        </div>

        <div className="border-t border-line bg-surface p-3">
          <div className="mx-auto max-w-3xl">
            <div className="rounded-lg border border-line bg-bg focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/25" data-testid="image-composer">
              {showSettings && model && (
                <div className="grid grid-cols-2 gap-3 border-b border-line/70 p-3 sm:grid-cols-4" data-testid="image-settings">
                  <Field label="Steps" htmlFor="img-steps" hint={`${model.supports.steps[0]}–${model.supports.steps[1]}`}>
                    <input id="img-steps" type="number" className="input" min={model.supports.steps[0]} max={model.supports.steps[1]} placeholder={d?.steps ? String(d.steps) : "default"} value={knobs.steps} onChange={(e) => setKnobs({ steps: e.target.value })} />
                  </Field>
                  {model.supports.cfg && (
                    <Field label="CFG scale" htmlFor="img-cfg" hint="1–15">
                      <input id="img-cfg" type="number" step="0.5" min={1} max={15} className="input" placeholder={d?.cfg ? String(d.cfg) : "default"} value={knobs.cfg} onChange={(e) => setKnobs({ cfg: e.target.value })} />
                    </Field>
                  )}
                  {model.supports.sampler && (
                    <Field label="Sampler" htmlFor="img-sampler">
                      <Select
                        id="img-sampler"
                        value={knobs.sampler}
                        onChange={(e) => setKnobs({ sampler: e.target.value })}
                        options={[{ value: "", label: `Default (${d?.sampler ?? "model"})` }, ...(q.data?.samplers ?? []).map((s) => ({ value: s, label: s }))]}
                      />
                    </Field>
                  )}
                  <Field label="Seed" htmlFor="img-seed" hint="empty = random">
                    <div className="flex gap-1">
                      <input id="img-seed" type="number" className="input" placeholder="random" value={knobs.seed} onChange={(e) => setKnobs({ seed: e.target.value })} />
                      <button type="button" aria-label="Random seed" title="Random seed" className="rounded-md border border-line px-2 text-muted hover:bg-surface2 hover:text-fg" onClick={() => setKnobs({ seed: String(Math.floor(Math.random() * 2 ** 31)) })}>
                        <Dices className="h-4 w-4" />
                      </button>
                    </div>
                  </Field>
                  {model.supports.negative && (
                    <Field className="col-span-2 sm:col-span-4" label="Negative prompt" htmlFor="img-neg" hint="Added to the model's defaults. Leave empty to use only the defaults.">
                      <input id="img-neg" className="input" placeholder={d?.negative || "things to avoid"} value={knobs.negative} onChange={(e) => setKnobs({ negative: e.target.value })} spellCheck={false} />
                    </Field>
                  )}
                  {d?.prefix && (
                    <p className="col-span-2 text-xs text-muted sm:col-span-4">
                      Added to the front of every prompt automatically: <span className="font-mono">{d.prefix.trim().replace(/,$/, "")}</span>
                    </p>
                  )}
                  <div className="col-span-2 sm:col-span-4">
                    <button type="button" className="text-xs text-accent underline underline-offset-2" onClick={() => model && setKnobsByModel((all) => { const n = { ...all, [model.id]: { ...EMPTY_KNOBS } }; lsSet(SETTINGS_KEY, JSON.stringify(n)); return n; })}>
                      Reset {model.label} settings to defaults
                    </button>
                  </div>
                </div>
              )}
              <textarea
                ref={ta}
                aria-label="Image prompt"
                rows={1}
                className="block max-h-[200px] w-full resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted/70"
                placeholder={model?.style === "tags" ? "Comma-separated tags, e.g. 1girl, solo, long hair, rain, night…  (Enter to generate)" : "Describe the image…  (Enter to generate, Shift+Enter for a newline)"}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={onKey}
              />
              <div className="flex flex-wrap items-center gap-3 border-t border-line/70 px-2 py-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                  Model
                  <Select
                    aria-label="Model"
                    className="!w-auto !py-0.5 !pl-2 text-xs"
                    value={model?.id ?? ""}
                    onChange={(e) => pickModel(e.target.value)}
                    options={models.length ? models.map((m) => ({ value: m.id, label: `${m.label}${m.up && m.present ? "" : " (unavailable)"}` })) : [{ value: "", label: q.isLoading ? "Loading…" : "No models" }]}
                  />
                </span>
                <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                  Size
                  <Select
                    aria-label="Size"
                    className="!w-auto !py-0.5 !pl-2 text-xs"
                    value={knobs.size}
                    onChange={(e) => setKnobs({ size: e.target.value })}
                    options={q.data?.sizes ?? ["1024x1024"]}
                  />
                </span>
                <button
                  type="button"
                  onClick={() => setShowSettings((v) => !v)}
                  aria-expanded={showSettings}
                  className={cn("inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs hover:bg-surface2 hover:text-fg", showSettings ? "bg-surface2 text-fg" : "text-muted")}
                  title="Steps, CFG, sampler, seed, negative prompt"
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
                  Settings
                </button>
                {status && <Badge tone={status.tone} dot>{status.text}</Badge>}
                {model && <span className="hidden max-w-[22rem] truncate text-xs text-muted lg:inline" title={model.about}>{model.about}</span>}
                <div className="ml-auto">
                  <Button size="sm" variant="primary" icon={busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} disabled={!prompt.trim() || busy || !ready} onClick={() => void send()} title={!ready ? "This model is not available" : undefined}>
                    {busy ? "Generating…" : "Generate"}
                  </Button>
                </div>
              </div>
            </div>
            {status && (status.tone === "err" || status.tone === "warn") && model && (
              <p className="mt-1.5 text-xs text-muted">
                {!model.up
                  ? `Start it with ${model.backend === "sdxl" ? "ops/imagegen-sdxl/run.sh" : "ops/imagegen/run.sh"} (expected at ${q.data?.services[model.backend].url ?? "its URL"}).`
                  : `Put the checkpoint file in data/models/sdxl/ (see ops/imagegen-sdxl/README.md).`}
              </p>
            )}
          </div>
        </div>
      </div>
    </Page>
  );
}

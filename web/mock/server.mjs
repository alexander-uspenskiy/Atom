// Tiny dependency-free mock of the Atom dashboard API (docs/DASHBOARD_API.md) for frontend development.
//   node mock/server.mjs            -> http://127.0.0.1:8788
//   ATOM_API=http://127.0.0.1:8788 pnpm dev
import http from "node:http";

const PORT = Number(process.env.MOCK_PORT ?? 8788);
const now = () => Date.now() / 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let idc = 100;
const uid = (p) => `${p}${++idc}`;
const clone = (o) => JSON.parse(JSON.stringify(o));

// ---------------------------------------------------------------- state
const agents = [
  { id: "a1", name: "News watcher", description: "Reads news front pages and summarizes them", instructions: "Be concise. Cite titles.", start_url: "https://news.ycombinator.com", allowed_domains: ["ycombinator.com"], allow_private: false, tools: null, skills: ["summarize-news"], memory_scope: "agent", thinking: "inherit", effort: "inherit", max_steps: null, temperature: null, profile: null, is_default: false, created_at: now() - 86400 * 9, updated_at: now() - 3600 },
  { id: "a0", name: "General browser agent", description: "Default agent for web tasks", instructions: "", start_url: null, allowed_domains: [], allow_private: false, tools: null, skills: [], memory_scope: "global", thinking: "auto", effort: "low", max_steps: 30, temperature: 0.6, profile: null, is_default: true, created_at: now() - 86400 * 20, updated_at: now() - 86400 },
];
const tools = [
  { name: "navigate", description: "Open a URL in the browser", side_effect: false },
  { name: "click", description: "Click an element by ref", side_effect: true },
  { name: "type", description: "Type text into an element", side_effect: true },
  { name: "extract", description: "Extract structured text from the page", side_effect: false },
  { name: "screenshot", description: "Capture a screenshot", side_effect: false },
  { name: "scroll", description: "Scroll the page", side_effect: false },
  { name: "finish", description: "Finish the run with a result", side_effect: false },
];
const skills = [
  { name: "summarize-news", description: "How to digest a news front page", when_to_use: "tasks about news digests", body: "# Steps\n1. Open the front page\n2. Read the **top 5** titles\n3. Summarize each in one line\n\n```text\nformat: - Title (points)\n```\n", enabled: true, created_by: "user", updated_at: now() - 7200 },
  { name: "fill-forms", description: "Careful form filling", when_to_use: "any form task", body: "# Forms\n- Never submit without confirmation\n", enabled: false, created_by: "assistant", updated_at: now() - 90000 },
];
let memories = [
  { id: "m1", title: "Preferred news sources", content: "User prefers HN and Ars Technica.", tags: ["preferences"], scope: "global", pinned: true, status: "active", source: "user", created_at: now() - 86400 * 5, updated_at: now() - 86400, last_used_at: now() - 600, use_count: 14 },
  { id: "m2", title: "Timezone", content: "User lives in New York (America/New_York).", tags: ["profile"], scope: "global", pinned: false, status: "active", source: "assistant", created_at: now() - 86400 * 3, updated_at: now() - 86400 * 3, last_used_at: null, use_count: 0 },
  { id: "m3", title: "HN digest format", content: "Use a bullet list with points in parentheses.", tags: ["format"], scope: "agent:a1", pinned: false, status: "pending", source: "assistant", created_at: now() - 300, updated_at: now() - 300, last_used_at: null, use_count: 0 },
];
let schedules = [
  { id: "s1", name: "Morning HN digest", agent_id: "a1", agent_name: "News watcher", task: "Report the top 5 Hacker News stories", start_url: null, trigger: { type: "cron", expr: "0 8 * * 1-5" }, timezone: "America/New_York", enabled: true, next_run_at: now() + 3 * 3600, last_run_at: now() - 21 * 3600, last_run_id: "run-old-1", last_status: "done", run_count: 12, created_by: "user", created_at: now() - 86400 * 9, updated_at: now() - 86400 },
  { id: "s2", name: "Hourly price check", agent_id: "a0", agent_name: "General browser agent", task: "Check the price of the RTX card on example.com/shop", start_url: "https://example.com/shop", trigger: { type: "interval", seconds: 3600 }, timezone: "America/New_York", enabled: true, next_run_at: now() + 900, last_run_at: now() - 2700, last_run_id: "run-old-2", last_status: "failed", run_count: 40, created_by: "assistant", created_at: now() - 86400 * 2, updated_at: now() - 3000 },
  { id: "s3", name: "One-off report", agent_id: "a1", agent_name: "News watcher", task: "Summarize the weekend news", start_url: null, trigger: { type: "once", at: "2026-11-08T08:00:00" }, timezone: "UTC", enabled: false, next_run_at: null, last_run_at: null, last_run_id: null, last_status: null, run_count: 0, created_by: "user", created_at: now() - 3600, updated_at: now() - 3600 },
];
let actions = [
  { id: "act1", kind: "create_schedule", summary: "Create schedule 'Morning HN digest' (cron 0 8 * * 1-5)", payload: { name: "Morning HN digest", agent_id: "a1", task: "Report the top 5 Hacker News stories", trigger: { type: "cron", expr: "0 8 * * 1-5" }, timezone: "America/New_York" }, status: "pending", created_by: "assistant", conversation_id: "c1", created_at: now() - 120, decided_at: null, result: null },
  { id: "act0", kind: "save_memory", summary: "Save memory 'Timezone'", payload: { title: "Timezone", content: "User lives in New York", scope: "global" }, status: "approved", created_by: "assistant", conversation_id: "c1", created_at: now() - 86400 * 3, decided_at: now() - 86400 * 3 + 30, result: { id: "m2" } },
];
const conversations = [
  { id: "c1", title: "Set up a morning digest", updated_at: now() - 120, messages: [
    { id: "msg1", role: "user", content: "Every weekday at 8am check Hacker News and give me the top 5 stories.", reasoning: null, tool_calls: null, tool_call_id: null, action_id: null, run_id: null, stats: null, created_at: now() - 130 },
    { id: "msg2", role: "assistant", content: "Sure — I'll propose a schedule for that. Please **approve** it below.\n\n```json\n{ \"cron\": \"0 8 * * 1-5\" }\n```", reasoning: "The user wants a recurring task. A cron of 0 8 * * 1-5 fits.", tool_calls: [{ id: "x1", name: "propose_schedule", arguments: { name: "Morning HN digest" } }], tool_call_id: null, action_id: "act1", run_id: null, stats: { prompt_tokens: 900, cached_tokens: 600, processed_tokens: 300, completion_tokens: 80, llm_seconds: 9.2, decode_tps: 9.1, prefill_tps: 85.0, think: false }, created_at: now() - 125 },
    { id: "msg3", role: "tool", content: "{\"ok\": true, \"action_id\": \"act1\"}", reasoning: null, tool_calls: null, tool_call_id: "x1", action_id: "act1", run_id: null, stats: null, created_at: now() - 124 },
  ] },
];
let settingsValues = { llm_base_url: "http://127.0.0.1:8080/v1", llm_model: "qwen3.8-27b", temperature: 0.6, top_p: 0.95, top_k: 20, presence_penalty: 0, agent_thinking: "auto", agent_effort: "low", chat_thinking: false, chat_effort: "low", max_steps: 30, max_wall_s: 900, compact_at_tokens: 24000, max_observation_tokens: 3000, max_read_tokens: 6000, headless: true, live_screenshots: true, max_concurrent_runs: 1, auto_approve_assistant_actions: false, memory_inject_k: 5, timezone: "America/New_York" };
const settingsDefaults = { ...settingsValues, temperature: 0.6, agent_thinking: "auto" };
const schema = [
  { key: "llm_base_url", label: "LLM base URL", group: "Model", type: "text", help: "OpenAI-compatible endpoint of the local model server." },
  { key: "llm_model", label: "Model name", group: "Model", type: "text" },
  { key: "temperature", label: "Temperature", group: "Model", type: "slider", min: 0, max: 2, step: 0.05, help: "Sampling temperature." },
  { key: "top_p", label: "Top-p", group: "Model", type: "slider", min: 0, max: 1, step: 0.01 },
  { key: "top_k", label: "Top-k", group: "Model", type: "number", min: 0, max: 200, step: 1 },
  { key: "presence_penalty", label: "Presence penalty", group: "Model", type: "slider", min: 0, max: 2, step: 0.1 },
  { key: "agent_thinking", label: "Agent thinking", group: "Agent", type: "select", options: ["off", "auto", "on"], help: "auto = off, escalate when stuck. on = always think (breaks prompt cache, slow)." },
  { key: "agent_effort", label: "Agent effort", group: "Agent", type: "select", options: ["low", "medium", "xhigh"] },
  { key: "max_steps", label: "Max steps", group: "Agent", type: "number", min: 1, max: 500, step: 1, help: "Hard cap on LLM steps per run." },
  { key: "max_wall_s", label: "Max wall time (s)", group: "Agent", type: "number", min: 30, max: 7200, step: 30 },
  { key: "compact_at_tokens", label: "Compact at tokens", group: "Agent", type: "number", min: 2000, max: 200000, step: 1000 },
  { key: "max_observation_tokens", label: "Max observation tokens", group: "Agent", type: "number", min: 200, max: 20000, step: 100 },
  { key: "max_read_tokens", label: "Max read tokens", group: "Agent", type: "number", min: 200, max: 40000, step: 100 },
  { key: "chat_thinking", label: "Chat thinking", group: "Chat", type: "boolean", help: "Thinking on breaks the prompt cache and is slower; leave off unless needed." },
  { key: "chat_effort", label: "Chat effort", group: "Chat", type: "select", options: ["low", "medium", "xhigh"] },
  { key: "memory_inject_k", label: "Memories injected", group: "Chat", type: "slider", min: 0, max: 20, step: 1 },
  { key: "auto_approve_assistant_actions", label: "Auto-approve assistant actions", group: "Chat", type: "boolean", help: "Skip the approval step. Not recommended." },
  { key: "headless", label: "Headless browser", group: "System", type: "boolean" },
  { key: "live_screenshots", label: "Live screenshots", group: "System", type: "boolean" },
  { key: "max_concurrent_runs", label: "Max concurrent runs", group: "System", type: "slider", min: 1, max: 4, step: 1 },
  { key: "timezone", label: "Timezone", group: "System", type: "text", help: "IANA name, e.g. America/New_York." },
];

// ---------------------------------------------------------------- runs
const runs = []; // newest first
const runEvents = new Map(); // id -> stored events (no tokens)
const subs = new Map(); // id -> Set<res>
const globalSubs = new Set();
const sims = new Map(); // id -> { stop: bool }

function summary(r) {
  const { _seq, ...rest } = r;
  return rest;
}
function sendSSE(res, obj) {
  res.write(`data: ${JSON.stringify(obj)}\n\n`);
}
function gbroadcast(obj) {
  for (const res of globalSubs) sendSSE(res, obj);
}
function newRun(task, agent, trigger = "manual", extra = {}) {
  const id = `20261106-${String(Math.floor(now()) % 1000000).padStart(6, "0")}-${Math.random().toString(16).slice(2, 8)}`;
  const r = { _seq: 0, id, task, agent_id: agent?.id ?? null, agent_name: agent?.name ?? null, schedule_id: null, trigger, status: "queued", success: null, result: null, error: null, queued_at: now(), started_at: null, finished_at: null, steps: 0, prompt_tokens: 0, cached_tokens: 0, processed_tokens: 0, completion_tokens: 0, llm_seconds: 0, tool_seconds: 0, wall_seconds: 0, thinking: "auto", effort: "low", current_url: null, last_screenshot: null, ...extra };
  runs.unshift(r);
  runEvents.set(id, []);
  subs.set(id, new Set());
  return r;
}
function emit(r, ev, store = true) {
  const e = { seq: ++r._seq, ts: now(), run_id: r.id, ...ev };
  if (store) runEvents.get(r.id).push(e);
  for (const res of subs.get(r.id) ?? []) sendSSE(res, e);
  return e;
}
const reasoningText = [
  "The task asks me to open the page and read the top stories. ",
  "First I should navigate to the start URL and see what the page looks like. ",
  "After that I can extract the visible titles and points. ",
  "I'll keep the answer short, one line per story, ",
  "and cite the points in parentheses as the memory suggests.",
];
async function simulate(r, script = "full") {
  const ctl = { stop: false };
  sims.set(r.id, ctl);
  const stopped = () => ctl.stop;
  r.status = "running";
  r.started_at = now();
  emit(r, { type: "run_status", status: "running" });
  gbroadcast({ type: "run_started", run: summary(r) });
  const plan = script === "short"
    ? [{ tool: null }]
    : [
        { tool: "navigate", args: { url: "https://news.ycombinator.com" } },
        { tool: "extract", args: { selector: ".titleline", max: 5 } },
        { tool: "click", args: { ref: "e12" } },
        { tool: null },
      ];
  let step = 0;
  for (const p of plan) {
    if (stopped()) break;
    step += 1;
    const think = step % 2 === 1;
    emit(r, { type: "step_start", step, think, effort: "low" });
    const t0 = now();
    if (think) {
      for (const chunk of reasoningText) {
        for (const w of chunk.match(/.{1,12}/g)) {
          if (stopped()) break;
          emit(r, { type: "token", step, channel: "reasoning", text: w }, false);
          await sleep(60);
        }
      }
    }
    const content = p.tool ? `Calling ${p.tool}…` : "Top stories:\n\n- **Show HN: A tiny local agent** (412)\n- *Why prefill matters* (310)\n- Rust 2.0 released (288)\n\n```py\nprint('done')\n```";
    for (const w of content.match(/.{1,6}/gs)) {
      if (stopped()) break;
      emit(r, { type: "token", step, channel: "content", text: w }, false);
      await sleep(50);
    }
    const prompt = 2000 + step * 300;
    const cached = step === 1 ? 0 : prompt - 250;
    const out = 40 + step * 25;
    const llm_seconds = now() - t0;
    emit(r, { type: "llm_end", step, prompt_tokens: prompt, cached_tokens: cached, processed_tokens: prompt - cached, completion_tokens: out, llm_seconds, prefill_ms: 800 + step * 200, decode_ms: Math.max(0, Math.round(llm_seconds * 1000) - 800), prefill_tps: 85, decode_tps: 10.4, finish_reason: p.tool ? "tool_calls" : "stop", content, tool_calls: p.tool ? [{ id: `call${step}`, name: p.tool, arguments: p.args }] : [] });
    Object.assign(r, { steps: step, prompt_tokens: r.prompt_tokens + prompt, cached_tokens: r.cached_tokens + cached, processed_tokens: r.processed_tokens + prompt - cached, completion_tokens: r.completion_tokens + out, llm_seconds: r.llm_seconds + llm_seconds });
    if (p.tool && !stopped()) {
      emit(r, { type: "tool_start", step, call_id: `call${step}`, name: p.tool, arguments: p.args });
      await sleep(p.tool === "navigate" ? 2500 : 1800);
      const ok = p.tool !== "click";
      const ts = p.tool === "navigate" ? 2.5 : 1.8;
      r.current_url = "https://news.ycombinator.com/";
      r.tool_seconds += ts;
      emit(r, { type: "tool_end", step, call_id: `call${step}`, name: p.tool, ok, result: ok ? `Loaded ${p.tool} OK\n1. Show HN: A tiny local agent (412)\n2. Why prefill matters (310)` : "Error: element e12 not found", tool_seconds: ts, url: r.current_url });
      r.last_screenshot = step;
      emit(r, { type: "screenshot", step, n: step, url: r.current_url, title: "Hacker News" });
    }
  }
  r.finished_at = now();
  r.wall_seconds = r.finished_at - r.started_at;
  r.status = stopped() ? "stopped" : "done";
  r.success = !stopped();
  r.result = stopped() ? null : "Top stories:\n\n- **Show HN: A tiny local agent** (412)\n- *Why prefill matters* (310)\n- Rust 2.0 released (288)";
  emit(r, { type: "run_finished", status: r.status, success: r.success, result: r.result, error: null, totals: { steps: r.steps, prompt_tokens: r.prompt_tokens, cached_tokens: r.cached_tokens, processed_tokens: r.processed_tokens, completion_tokens: r.completion_tokens, llm_seconds: r.llm_seconds, tool_seconds: r.tool_seconds, wall_seconds: r.wall_seconds } });
  for (const res of subs.get(r.id) ?? []) res.end();
  subs.get(r.id)?.clear();
  gbroadcast({ type: "run_finished", run: summary(r) });
  sims.delete(r.id);
}
function seedFinished(task, agent, status, ago, trigger = "manual") {
  const r = newRun(task, agent, trigger);
  const t = now() - ago;
  Object.assign(r, { status, success: status === "done", result: status === "done" ? "Done." : null, error: status === "failed" ? "Timeout waiting for selector" : null, queued_at: t - 2, started_at: t, finished_at: t + 40, steps: 6, prompt_tokens: 14200, cached_tokens: 12900, processed_tokens: 1300, completion_tokens: 410, llm_seconds: 33.3, tool_seconds: 1.7, wall_seconds: 40, last_screenshot: 2, current_url: "https://news.ycombinator.com" });
  const ev = runEvents.get(r.id);
  let seq = 0;
  const push = (e) => ev.push({ seq: ++seq, ts: t + seq, run_id: r.id, ...e });
  push({ type: "run_status", status: "running" });
  push({ type: "step_start", step: 1, think: false, effort: "low" });
  push({ type: "llm_end", step: 1, prompt_tokens: 2150, cached_tokens: 1989, processed_tokens: 161, completion_tokens: 28, llm_seconds: 3.4, prefill_ms: 1500, decode_ms: 2600, prefill_tps: 90, decode_tps: 10.8, finish_reason: "tool_calls", content: "", tool_calls: [{ id: "c1", name: "navigate", arguments: { url: "https://news.ycombinator.com" } }] });
  push({ type: "tool_start", step: 1, call_id: "c1", name: "navigate", arguments: { url: "https://news.ycombinator.com" } });
  push({ type: "tool_end", step: 1, call_id: "c1", name: "navigate", ok: true, result: "Loaded", tool_seconds: 0.4, url: "https://news.ycombinator.com" });
  push({ type: "screenshot", step: 1, n: 1, url: "https://news.ycombinator.com", title: "Hacker News" });
  push({ type: "run_finished", status, success: status === "done", result: r.result, error: r.error, totals: {} });
  r._seq = seq;
  return r;
}
function detail(r) {
  const evs = runEvents.get(r.id) ?? [];
  const steps = [];
  let i = 0;
  for (const e of evs) {
    if (e.type === "llm_end") steps.push({ idx: i++, kind: "llm", name: "llm", args: null, result: e.content ?? "", ok: true, url: null, think: false, prompt_tokens: e.prompt_tokens, cached_tokens: e.cached_tokens, processed_tokens: e.processed_tokens, completion_tokens: e.completion_tokens, llm_seconds: e.llm_seconds, prefill_ms: e.prefill_ms, decode_ms: e.decode_ms, decode_tps: e.decode_tps, tool_seconds: 0, ts: e.ts, screenshot: null });
    if (e.type === "tool_end") {
      const start = evs.find((x) => x.type === "tool_start" && x.call_id === e.call_id);
      const shot = evs.find((x) => x.type === "screenshot" && x.step === e.step);
      steps.push({ idx: i++, kind: "tool", name: e.name, args: start?.arguments, result: e.result, ok: e.ok, url: e.url, think: false, tool_seconds: e.tool_seconds, ts: e.ts, screenshot: shot?.n ?? null });
    }
  }
  return { run: summary(r), steps, events_url: `/api/runs/${r.id}/events` };
}

// ---------------------------------------------------------------- stats
function stats(days) {
  const by_day = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    const input = 40000 + ((i * 7919) % 30000);
    by_day.push({ day: d, runs: 3 + ((i * 5) % 7), input, cached: Math.round(input * 0.86), output: 1800 + ((i * 313) % 1500), llm_seconds: 120 + ((i * 37) % 90) });
  }
  const done = Math.round(days * 4.6);
  return { days, runs: { total: done + 6, done, failed: 3, budget: 2, stopped: 1, success_rate: done / (done + 6) }, tokens: { input: 410000, cached: 360000, processed: 50000, output: 21000, cache_hit_rate: 0.88 }, timing: { avg_wall_s: 58.2, avg_llm_s_per_step: 4.1, avg_decode_tps: 9.4, avg_prefill_tps: 88 }, by_day, by_agent: [{ agent_id: "a1", agent_name: "News watcher", runs: 21, success_rate: 0.95, input: 250000, output: 12000, avg_wall_s: 40 }, { agent_id: "a0", agent_name: "General browser agent", runs: 19, success_rate: 0.7, input: 160000, output: 9000, avg_wall_s: 78 }], slowest_runs: runs.slice(0, 4).map(summary) };
}

// ---------------------------------------------------------------- http helpers
const json = (res, code, body) => {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(body === undefined ? "" : JSON.stringify(body));
};
const err = (res, code, detail) => json(res, code, { detail });
async function readBody(req) {
  let s = "";
  for await (const c of req) s += c;
  try { return s ? JSON.parse(s) : {}; } catch { return {}; }
}
function sseHeaders(res) {
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", Connection: "keep-alive", "X-Accel-Buffering": "no" });
  res.write(": hello\n\n");
}
function status() {
  return { version: "0.2.0-mock", llm: { healthy: true, base_url: "http://127.0.0.1:8080/v1", model: "qwen3.8-27b", slots: [{ id: 0, busy: runs.some((r) => r.status === "running"), n_ctx: 32768, role: "agent" }, { id: 1, busy: false, n_ctx: 32768, role: "extract" }, { id: 2, busy: false, n_ctx: 32768, role: "chat" }] }, runs: { running: runs.filter((r) => r.status === "running").map((r) => r.id), queued: runs.filter((r) => r.status === "queued").length, max_concurrent: 1 }, scheduler: { running: true, jobs: schedules.filter((s) => s.enabled).length }, pending_actions: actions.filter((a) => a.status === "pending").length };
}
function previewTrigger(t, tz, count) {
  const next = [];
  let desc = "";
  const base = new Date();
  if (t.type === "cron") {
    const parts = String(t.expr ?? "").trim().split(/\s+/);
    if (parts.length !== 5 || !/^[\d*\/,\-]+$/.test(parts.join(""))) return null;
    desc = `Cron ${t.expr} (${tz})`;
    if (t.expr === "0 8 * * 1-5") desc = "At 08:00, Monday through Friday";
    for (let i = 1; next.length < count; i++) { const d = new Date(base.getTime() + i * 86400000); d.setUTCHours(8, 0, 0, 0); if (![0, 6].includes(d.getUTCDay())) next.push(d.toISOString().replace(".000Z", "-05:00")); }
  } else if (t.type === "interval") {
    if (!(t.seconds > 0)) return null;
    desc = `Every ${t.seconds} seconds`;
    for (let i = 1; i <= count; i++) next.push(new Date(base.getTime() + i * t.seconds * 1000).toISOString());
  } else {
    if (!t.at) return null;
    desc = `Once at ${t.at}`;
    next.push(t.at + "-05:00");
  }
  return { next, description: desc };
}

// ---------------------------------------------------------------- chat
async function chatStream(req, res, conv, body) {
  sseHeaders(res);
  let closed = false;
  res.on("close", () => { closed = true; });
  const send = (o) => !closed && sendSSE(res, o);
  const text = String(body.content ?? "");
  conv.messages.push({ id: uid("msg"), role: "user", content: text, reasoning: null, tool_calls: null, tool_call_id: null, action_id: null, run_id: null, stats: null, created_at: now() });
  if (!conv.title) conv.title = text.slice(0, 40);
  const mid = uid("msg");
  send({ type: "message_start", message_id: mid });
  const t0 = now();
  let reasoning = "";
  if (body.thinking) {
    for (const w of "The user asks something. Let me think about what tools to use and how to answer briefly. ".match(/.{1,8}/g)) { if (closed) return; reasoning += w; send({ type: "token", channel: "reasoning", text: w }); await sleep(40); }
  }
  const wantsSchedule = /schedul|every|daily|weekday/i.test(text);
  const wantsRun = /\brun\b|browse|open /i.test(text);
  const tool_calls = [];
  let action_id = null, run_id = null;
  if (wantsSchedule) {
    const call = { id: uid("call"), name: "propose_schedule", arguments: { name: "Mock schedule", cron: "0 8 * * 1-5" } };
    tool_calls.push(call);
    send({ type: "tool_call", ...call });
    await sleep(500);
    const a = { id: uid("act"), kind: "create_schedule", summary: "Create schedule 'Mock schedule' (cron 0 8 * * 1-5)", payload: { name: "Mock schedule", agent_id: "a1", task: text, trigger: { type: "cron", expr: "0 8 * * 1-5" }, timezone: "America/New_York" }, status: "pending", created_by: "assistant", conversation_id: conv.id, created_at: now(), decided_at: null, result: null };
    actions.unshift(a);
    action_id = a.id;
    send({ type: "tool_result", id: call.id, name: call.name, ok: true, result: { action_id: a.id } });
    send({ type: "action_proposed", action: a });
    gbroadcast({ type: "action_pending", action: a });
  }
  if (wantsRun) {
    const r = newRun(text, agents[1], "chat");
    run_id = r.id;
    simulate(r);
    send({ type: "run_started", run_id: r.id });
  }
  const answer = wantsSchedule
    ? "I've drafted a schedule. Please **approve** the card above to activate it.\n\n| Field | Value |\n|---|---|\n| cron | `0 8 * * 1-5` |\n"
    : "Here is a short answer with `inline code` and a block:\n\n```python\ndef hello():\n    return 'atom'\n```\n\n- point one\n- point two\n";
  let content = "";
  for (const w of answer.match(/.{1,5}/gs)) { if (closed) return; content += w; send({ type: "token", channel: "content", text: w }); await sleep(30); }
  const secs = now() - t0;
  const stats = { prompt_tokens: 900, cached_tokens: 600, processed_tokens: 300, completion_tokens: 80, llm_seconds: Number(secs.toFixed(1)), decode_tps: 9.1, prefill_tps: 85, think: !!body.thinking };
  send({ type: "llm_end", ...stats });
  const msg = { id: mid, role: "assistant", content, reasoning: reasoning || null, tool_calls: tool_calls.length ? tool_calls : null, tool_call_id: null, action_id, run_id, stats, created_at: now() };
  conv.messages.push(msg);
  conv.updated_at = now();
  send({ type: "message_end", message: msg });
  send({ type: "done" });
  res.end();
}

// ---------------------------------------------------------------- router
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;
  const m = req.method;
  const q = url.searchParams;
  let g;
  try {
    if (!p.startsWith("/api/")) return err(res, 404, "not found");
    if (p === "/api/status") return json(res, 200, status());
    if (p === "/api/events") {
      sseHeaders(res);
      globalSubs.add(res);
      sendSSE(res, { type: "status", status: status() });
      const t = setInterval(() => sendSSE(res, { type: "status", status: status() }), 5000);
      res.on("close", () => { clearInterval(t); globalSubs.delete(res); });
      return;
    }
    if (p === "/api/settings") {
      if (m === "PUT") {
        const b = await readBody(req);
        for (const k of Object.keys(b.values ?? {})) if (!(k in settingsValues)) return err(res, 422, `unknown setting ${k}`);
        Object.assign(settingsValues, b.values);
      }
      return json(res, 200, { values: settingsValues, defaults: settingsDefaults, schema });
    }
    if (p === "/api/tools") return json(res, 200, tools);
    if (p === "/api/agents") {
      if (m === "POST") { const b = await readBody(req); const a = { ...b, id: uid("a"), is_default: false, created_at: now(), updated_at: now() }; agents.push(a); return json(res, 200, a); }
      return json(res, 200, agents);
    }
    if ((g = p.match(/^\/api\/agents\/([^/]+)\/run$/)) && m === "POST") {
      const a = agents.find((x) => x.id === g[1]);
      if (!a) return err(res, 404, "agent not found");
      const b = await readBody(req);
      const r = newRun(b.task, a, "manual", { thinking: b.overrides?.thinking ?? "auto", effort: b.overrides?.effort ?? "low" });
      simulate(r);
      return json(res, 202, { run_id: r.id });
    }
    if ((g = p.match(/^\/api\/agents\/([^/]+)$/))) {
      const i = agents.findIndex((x) => x.id === g[1]);
      if (i < 0) return err(res, 404, "agent not found");
      if (m === "DELETE") { if (agents[i].is_default) return err(res, 409, "default agent cannot be deleted"); agents.splice(i, 1); return json(res, 200, { ok: true }); }
      if (m === "PUT") { agents[i] = { ...agents[i], ...(await readBody(req)), id: agents[i].id, updated_at: now() }; }
      return json(res, 200, agents[i]);
    }
    if (p === "/api/runs") {
      let items = runs.filter((r) => (!q.get("status") || r.status === q.get("status")) && (!q.get("agent_id") || r.agent_id === q.get("agent_id")) && (!q.get("q") || r.task.toLowerCase().includes(q.get("q").toLowerCase())));
      const total = items.length;
      const off = Number(q.get("offset") ?? 0), lim = Number(q.get("limit") ?? 50);
      return json(res, 200, { items: items.slice(off, off + lim).map(summary), total });
    }
    if ((g = p.match(/^\/api\/runs\/([^/]+)\/events$/))) {
      const r = runs.find((x) => x.id === g[1]);
      if (!r) return err(res, 404, "run not found");
      sseHeaders(res);
      for (const e of runEvents.get(r.id)) sendSSE(res, e);
      if (["queued", "running"].includes(r.status)) {
        subs.get(r.id).add(res);
        res.on("close", () => subs.get(r.id)?.delete(res));
        if (globalThis.__drop) setTimeout(() => !res.writableEnded && res.end(), 5000); // test: force a client reconnect (replay)
        const t = setInterval(() => !res.writableEnded && res.write(": ping\n\n"), 15000);
        res.on("close", () => clearInterval(t));
      } else res.end();
      return;
    }
    if ((g = p.match(/^\/api\/runs\/([^/]+)\/stop$/)) && m === "POST") {
      const r = runs.find((x) => x.id === g[1]);
      if (!r) return err(res, 404, "run not found");
      if (!["queued", "running"].includes(r.status)) return err(res, 409, "run is not active");
      console.log(`[mock] STOP requested for ${r.id}`);
      globalThis.__stops = (globalThis.__stops ?? 0) + 1;
      const s = sims.get(r.id);
      if (s) s.stop = true;
      return json(res, 200, summary(r));
    }
    if ((g = p.match(/^\/api\/runs\/([^/]+)\/shots\/(\d+)\.jpg$/))) {
      const n = Number(g[2]);
      const hue = (n * 47) % 360;
      res.writeHead(200, { "Content-Type": "image/svg+xml" });
      return res.end(`<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800"><rect width="1280" height="800" fill="#f6f6ef"/><rect width="1280" height="56" fill="hsl(${hue},70%,50%)"/><text x="24" y="38" font-family="sans-serif" font-size="28" fill="#fff" font-weight="700">Hacker News - mock screenshot #${n}</text>${[1, 2, 3, 4, 5, 6, 7, 8].map((i) => `<text x="40" y="${100 + i * 70}" font-family="sans-serif" font-size="26" fill="#222">${i}. Story title number ${i} (${400 - i * 31} points)</text>`).join("")}</svg>`);
    }
    if ((g = p.match(/^\/api\/runs\/([^/]+)\/trace\.zip$/))) { res.writeHead(200, { "Content-Type": "application/zip" }); return res.end("PK"); }
    if ((g = p.match(/^\/api\/runs\/([^/]+)$/))) {
      const r = runs.find((x) => x.id === g[1]);
      return r ? json(res, 200, detail(r)) : err(res, 404, "run not found");
    }
    if (p === "/api/schedules/preview" && m === "POST") {
      const b = await readBody(req);
      const pr = previewTrigger(b.trigger ?? {}, b.timezone, b.count ?? 5);
      return pr ? json(res, 200, pr) : err(res, 422, "Invalid trigger");
    }
    if (p === "/api/schedules") {
      if (m === "POST") {
        const b = await readBody(req);
        if (!previewTrigger(b.trigger ?? {}, b.timezone, 1)) return err(res, 422, "Invalid cron expression");
        const s = { ...b, id: uid("s"), agent_name: agents.find((a) => a.id === b.agent_id)?.name ?? null, next_run_at: now() + 3600, last_run_at: null, last_run_id: null, last_status: null, run_count: 0, created_by: "user", created_at: now(), updated_at: now() };
        schedules.push(s);
        return json(res, 200, s);
      }
      return json(res, 200, schedules);
    }
    if ((g = p.match(/^\/api\/schedules\/([^/]+)\/(run|toggle)$/)) && m === "POST") {
      const s = schedules.find((x) => x.id === g[1]);
      if (!s) return err(res, 404, "schedule not found");
      if (g[2] === "toggle") { s.enabled = !!(await readBody(req)).enabled; return json(res, 200, s); }
      const r = newRun(s.task, agents.find((a) => a.id === s.agent_id), "schedule", { schedule_id: s.id });
      simulate(r, "short");
      return json(res, 202, { run_id: r.id });
    }
    if ((g = p.match(/^\/api\/schedules\/([^/]+)$/))) {
      const i = schedules.findIndex((x) => x.id === g[1]);
      if (i < 0) return err(res, 404, "schedule not found");
      if (m === "DELETE") { schedules.splice(i, 1); return json(res, 200, { ok: true }); }
      if (m === "PUT") schedules[i] = { ...schedules[i], ...(await readBody(req)), id: schedules[i].id, updated_at: now() };
      return json(res, 200, schedules[i]);
    }
    if (p === "/api/memories") {
      if (m === "POST") { const b = await readBody(req); const x = { ...b, id: uid("m"), status: "active", source: "user", created_at: now(), updated_at: now(), last_used_at: null, use_count: 0 }; memories.unshift(x); return json(res, 200, x); }
      const qq = (q.get("q") ?? "").toLowerCase();
      return json(res, 200, memories.filter((x) => (!qq || (x.title + x.content).toLowerCase().includes(qq)) && (!q.get("scope") || x.scope === q.get("scope")) && (q.get("pinned") !== "true" || x.pinned) && (!q.get("status") || x.status === q.get("status"))));
    }
    if ((g = p.match(/^\/api\/memories\/([^/]+)$/))) {
      const i = memories.findIndex((x) => x.id === g[1]);
      if (i < 0) return err(res, 404, "memory not found");
      if (m === "DELETE") { memories.splice(i, 1); return json(res, 200, { ok: true }); }
      if (m === "PUT") memories[i] = { ...memories[i], ...(await readBody(req)), updated_at: now() };
      return json(res, 200, memories[i]);
    }
    if (p === "/api/skills") {
      if (m === "POST") { const b = await readBody(req); if (!/^[a-z0-9-]+$/.test(b.name ?? "")) return err(res, 422, "invalid name"); if (skills.some((s) => s.name === b.name)) return err(res, 409, "skill exists"); const s = { ...b, created_by: "user", updated_at: now() }; skills.push(s); return json(res, 200, s); }
      return json(res, 200, skills);
    }
    if ((g = p.match(/^\/api\/skills\/([^/]+)$/))) {
      const i = skills.findIndex((x) => x.name === g[1]);
      if (i < 0) return err(res, 404, "skill not found");
      if (m === "DELETE") { skills.splice(i, 1); return json(res, 200, { ok: true }); }
      if (m === "PUT") skills[i] = { ...skills[i], ...(await readBody(req)), name: skills[i].name, updated_at: now() };
      return json(res, 200, skills[i]);
    }
    if (p === "/api/actions") return json(res, 200, actions.filter((a) => !q.get("status") || a.status === q.get("status")));
    if ((g = p.match(/^\/api\/actions\/([^/]+)\/(approve|reject)$/)) && m === "POST") {
      const a = actions.find((x) => x.id === g[1]);
      if (!a) return err(res, 404, "action not found");
      const b = await readBody(req);
      if (b.payload) a.payload = b.payload;
      a.status = g[2] === "approve" ? "approved" : "rejected";
      a.decided_at = now();
      gbroadcast({ type: "action_decided", action: a });
      return json(res, 200, a);
    }
    if (p === "/api/conversations") {
      if (m === "POST") { const c = { id: uid("c"), title: (await readBody(req)).title ?? null, updated_at: now(), messages: [] }; conversations.unshift(c); return json(res, 200, { id: c.id, title: c.title, updated_at: c.updated_at, message_count: 0 }); }
      return json(res, 200, conversations.map((c) => ({ id: c.id, title: c.title, updated_at: c.updated_at, message_count: c.messages.length })));
    }
    if ((g = p.match(/^\/api\/conversations\/([^/]+)\/messages$/)) && m === "POST") {
      const c = conversations.find((x) => x.id === g[1]);
      if (!c) return err(res, 404, "conversation not found");
      return chatStream(req, res, c, await readBody(req));
    }
    if ((g = p.match(/^\/api\/conversations\/([^/]+)$/))) {
      const i = conversations.findIndex((x) => x.id === g[1]);
      if (i < 0) return err(res, 404, "conversation not found");
      if (m === "DELETE") { conversations.splice(i, 1); return json(res, 200, { ok: true }); }
      if (m === "PUT") { conversations[i].title = (await readBody(req)).title; }
      return json(res, 200, m === "PUT" ? { id: conversations[i].id, title: conversations[i].title } : { id: conversations[i].id, title: conversations[i].title, messages: conversations[i].messages });
    }
    if (p === "/api/stats/summary") return json(res, 200, stats(Number(q.get("days") ?? 7)));
    if (p === "/api/__mock/drop") { globalThis.__drop = q.get("on") === "1"; return json(res, 200, { drop: globalThis.__drop }); }
    if (p === "/api/__mock/stops") return json(res, 200, { stops: globalThis.__stops ?? 0 });
    return err(res, 404, `no mock for ${m} ${p}`);
  } catch (e) {
    console.error(e);
    if (!res.headersSent) err(res, 500, String(e));
  }
});

// seed some history + one live run
const [a1, a0] = agents;
seedFinished("Report the top 5 Hacker News stories", a1, "done", 3600 * 21, "schedule");
seedFinished("Check the price of the RTX card", a0, "failed", 2700, "schedule");
seedFinished("Summarize the Ars Technica front page", a1, "done", 7200);
seedFinished("Find the cheapest flight to Lisbon", a0, "done", 86400 * 2);
{
  const r = newRun("Open Hacker News and report the top stories", a1, "manual");
  simulate(r);
}
server.listen(PORT, "127.0.0.1", () => console.log(`[mock] Atom API mock on http://127.0.0.1:${PORT}`));

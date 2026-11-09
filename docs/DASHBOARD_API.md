# Atom dashboard — API contract (v1)

Backend: FastAPI on `http://127.0.0.1:8787`. All routes are under `/api`, JSON in/out unless noted.
Timestamps are Unix seconds (float). IDs are strings. Errors: HTTP 4xx/5xx with `{"detail": "message"}`.
The built frontend (`web/dist`) is served by the backend at `/`; in dev, Vite proxies `/api` to the backend.
SSE = `text/event-stream`, each message is `data: <json>\n\n`; heartbeat comment lines `: ping` every 15 s.

## System

### GET /api/status
```json
{ "version": "0.2.0",
  "llm": {"healthy": true, "base_url": "http://127.0.0.1:8080/v1", "model": "qwen3.8-27b",
          "slots": [{"id": 0, "busy": false, "n_ctx": 32768, "role": "agent"},
                    {"id": 1, "busy": false, "n_ctx": 32768, "role": "extract"},
                    {"id": 2, "busy": false, "n_ctx": 32768, "role": "chat"}]},
  "runs": {"running": ["run-id"], "queued": 0, "max_concurrent": 1},
  "scheduler": {"running": true, "jobs": 3},
  "pending_actions": 1 }
```

### GET /api/events (SSE, global)
Events: `{"type": "run_queued"|"run_started"|"run_finished", "run": RunSummary}`,
`{"type": "schedule_fired", "schedule_id": "...", "run_id": "..."}`,
`{"type": "action_pending", "action": PendingAction}`, `{"type": "action_decided", "action": PendingAction}`,
`{"type": "status", "status": <same as GET /api/status>}` (every ~5 s).

## Settings

### GET /api/settings
```json
{ "values": {"temperature": 0.6, "agent_thinking": "auto", ...},
  "defaults": {"temperature": 0.6, ...},
  "schema": [ {"key": "agent_thinking", "label": "Agent thinking", "group": "Model",
               "type": "select", "options": ["off","auto","on"],
               "help": "auto = off, escalate when stuck. on = always think (breaks prompt cache, slow)."} ] }
```
`type` is one of `text | number | boolean | select | slider`; number/slider carry `min`, `max`, `step`.
The UI MUST render the settings form generically from `schema` (grouped by `group`, in order).
Keys: `llm_base_url`, `llm_model`, `temperature`, `top_p`, `top_k`, `presence_penalty`,
`agent_thinking` (off|auto|on), `agent_effort` (low|medium|xhigh), `chat_thinking` (boolean),
`chat_effort`, `max_steps`, `max_wall_s`, `compact_at_tokens`, `max_observation_tokens`, `max_read_tokens`,
`chat_compact_at`, `llm_profile`, `headless`, `live_screenshots`, `agent_vision`, `max_concurrent_runs`, `auto_approve_assistant_actions`, `memory_inject_k`,
`timezone`.

### PUT /api/settings   body `{"values": {"temperature": 0.7}}` → same shape as GET. Unknown keys → 422.

## Models

Model profiles, each a separate llama-server (`ops/llama-server.sh <profile>`).

- `GET /api/models` → `{"active": "qwen", "models": [ModelInfo]}` (id, label, detail, model, base_url, size_gb, installed, running, managed, download progress).
- `POST /api/models/{profile}/activate` body `{"start": true}` → make it the default; starts its server if downloaded and not running.
- `POST /api/models/{profile}/{start|stop|download}` → same payload. Unknown profile/action → 404; not downloaded → 409; stop of a server Atom did not start → 409.

## Agents (saved configurations of the web agent)

`Agent`:
```json
{ "id": "a1", "name": "News watcher", "description": "...", "instructions": "extra system prompt text",
  "start_url": null, "allowed_domains": ["ycombinator.com"], "allow_private": false,
  "tools": null, "skills": ["summarize-news"], "memory_scope": "agent", "model": null,
  "thinking": "inherit", "effort": "inherit", "max_steps": null, "temperature": null, "profile": null,
  "is_default": false, "created_at": 0, "updated_at": 0 }
```
`tools`: null = all tools, else array of tool names. `memory_scope`: `none | global | agent`.
`model`: null (use the default) or a model profile id (`qwen | arete`); `thinking`: `inherit | off | auto | on`; `effort`: `inherit | low | medium | xhigh`.

- `GET /api/agents` → `Agent[]`;  `POST /api/agents` (Agent without id/timestamps) → `Agent`
- `GET|PUT|DELETE /api/agents/{id}` (default agent cannot be deleted → 409)
- `GET /api/tools` → `[{"name": "click", "description": "...", "side_effect": false}]`
- `POST /api/agents/{id}/run` body `{"task": "...", "start_url": null, "overrides": {"thinking": "on", "effort": "low", "max_steps": 10}, "images": ["<upload id>"]}` → `{"run_id": "..."}` (HTTP 202). `images` is optional; the agent sees them with the task (422 if the model server has no vision projector). Run summaries include `images: [ids]`.

## Runs

`RunSummary`:
```json
{ "id": "20261106-150000-ab12cd", "task": "...", "agent_id": "a1", "agent_name": "News watcher",
  "schedule_id": null, "trigger": "manual|schedule|chat|api",
  "status": "queued|running|done|failed|budget|stopped", "success": true, "result": "text or JSON string",
  "error": null, "queued_at": 0, "started_at": 0, "finished_at": 0, "steps": 5,
  "prompt_tokens": 11340, "cached_tokens": 10700, "processed_tokens": 613, "completion_tokens": 235,
  "llm_seconds": 33.3, "tool_seconds": 1.7, "wall_seconds": 36.1,
  "thinking": "auto", "effort": "low", "current_url": "http://...", "last_screenshot": 4 }
```
`prompt_tokens` = total input tokens; `cached_tokens` = served from prompt cache; `processed_tokens` = actually evaluated
(prompt = cached + processed).

- `GET /api/runs?status=&agent_id=&schedule_id=&q=&limit=50&offset=0` → `{"items": RunSummary[], "total": 0}` (newest first)
- `GET /api/runs/{id}` → `{"run": RunSummary, "steps": Step[], "events_url": "/api/runs/{id}/events"}`
- `POST /api/runs/{id}/stop` → `RunSummary` (queued or running runs only; else 409)
- `GET /api/runs/{id}/shots/{n}.jpg` (image) ; `GET /api/runs/{id}/trace.zip` (Playwright trace download)
- `GET /api/runs/{id}/events` (SSE): first replays all stored events in order, then streams live; ends after `run_finished`.

`Step` (stored, for the timeline):
```json
{ "idx": 3, "kind": "llm|tool|compact|note", "name": "click", "args": {"ref": "e12"}, "result": "preview<=2000 chars",
  "ok": true, "url": "...", "think": false, "prompt_tokens": 2150, "cached_tokens": 1989, "processed_tokens": 161,
  "completion_tokens": 28, "llm_seconds": 3.4, "prefill_ms": 1500, "decode_ms": 2600, "decode_tps": 10.8,
  "tool_seconds": 0.4, "ts": 0, "screenshot": 3 }
```

### Run event stream
Every event: `{"seq": 17, "ts": 0, "run_id": "...", "type": "...", ...}`.
- `run_status` `{status}` — queued/running/...
- `step_start` `{step, think, effort}` — an LLM call began
- `token` `{step, channel: "content"|"reasoning", text}` — live text deltas (batched ~10/s; NOT replayed)
- `llm_end` `{step, prompt_tokens, cached_tokens, processed_tokens, completion_tokens, llm_seconds, prefill_ms, decode_ms, prefill_tps, decode_tps, finish_reason, content, tool_calls: [{id, name, arguments}]}`
- `tool_start` `{step, call_id, name, arguments}`
- `tool_end` `{step, call_id, name, ok, result, tool_seconds, url}`
- `screenshot` `{step, n, url, title}` → image at `/api/runs/{id}/shots/{n}.jpg`
- `compact` `{step, summarized_actions}`
- `run_finished` `{status, success, result, error, totals: {steps, prompt_tokens, cached_tokens, processed_tokens, completion_tokens, llm_seconds, tool_seconds, wall_seconds}}`

## Schedules

`Schedule`:
```json
{ "id": "s1", "name": "Morning HN digest", "agent_id": "a1", "agent_name": "News watcher",
  "task": "Report the top 5 Hacker News stories", "start_url": null,
  "trigger": {"type": "cron", "expr": "0 8 * * 1-5"},
  "timezone": "America/New_York", "enabled": true, "next_run_at": 0, "last_run_at": 0,
  "last_run_id": "...", "last_status": "done", "run_count": 12,
  "created_by": "user|assistant", "created_at": 0, "updated_at": 0 }
```
`trigger` is one of `{"type":"cron","expr":"m h dom mon dow"}`, `{"type":"interval","seconds":3600}`, `{"type":"once","at":"2026-11-07T08:00:00"}` (local time in `timezone`).

- `GET /api/schedules` → `Schedule[]`; `POST /api/schedules` → `Schedule` (validates the trigger; 422 on bad cron). Optional `images: [upload ids]` are attached to every run of the schedule (also on `PUT`; `[]` clears them)
- `GET|PUT|DELETE /api/schedules/{id}`
- `POST /api/schedules/{id}/run` → `{"run_id": "..."}` (run now, 202)
- `POST /api/schedules/{id}/toggle` body `{"enabled": false}` → `Schedule`
- `POST /api/schedules/preview` body `{"trigger": {...}, "timezone": "...", "count": 5}` → `{"next": ["2026-11-07T08:00:00-05:00", ...], "description": "At 08:00, Monday through Friday"}`
  For an invalid trigger this answers **200** with `{"next": [], "description": "", "error": "message"}` (no 4xx while the user is typing).

## Memory

`Memory`:
```json
{ "id": "m1", "title": "Preferred news sources", "content": "User prefers HN and Ars Technica.",
  "tags": ["preferences"], "scope": "global", "pinned": false, "status": "active",
  "source": "user", "created_at": 0, "updated_at": 0, "last_used_at": null, "use_count": 0 }
```
`scope`: `global` or `agent:<agent_id>`. `status`: `active | pending` (assistant-proposed, awaiting approval). `pinned` memories are always injected.
- `GET /api/memories?q=&scope=&pinned=&status=&limit=100` → `Memory[]` (`q` = full-text search, ranked)
- `POST /api/memories` → `Memory`; `PUT|DELETE /api/memories/{id}`

## Skills (reusable procedures; stored as `data/skills/<name>/SKILL.md`)

`Skill`:
```json
{ "name": "summarize-news", "description": "How to digest a news front page", "when_to_use": "tasks about news digests",
  "body": "# Steps\n1. ...", "enabled": true, "created_by": "user|assistant", "updated_at": 0 }
```
- `GET /api/skills` → `Skill[]`; `POST /api/skills` → `Skill` (name is a slug `[a-z0-9-]+`; 409 if it exists)
- `GET|PUT|DELETE /api/skills/{name}`

## Approvals (actions the assistant proposes; a human decides)

`PendingAction`:
```json
{ "id": "act1", "kind": "create_schedule|create_agent|create_skill|save_memory|update_schedule|delete_schedule",
  "summary": "Create schedule 'Morning HN digest' (cron 0 8 * * 1-5)", "payload": {"...": "the object to create"},
  "status": "pending|approved|rejected|failed", "created_by": "assistant", "conversation_id": "c1",
  "created_at": 0, "decided_at": null, "result": null }
```
- `GET /api/actions?status=pending` → `PendingAction[]`
- `POST /api/actions/{id}/approve` body `{"payload": {...optional edited payload}}` → `PendingAction` (executes it)
- `POST /api/actions/{id}/reject` → `PendingAction`

## Chat (talk to the model; it can propose schedules/agents/skills/memories and start runs)

`Message`:
```json
{ "id": "msg1", "role": "user|assistant|tool", "content": "text", "reasoning": "thinking text or null",
  "tool_calls": [{"id": "x", "name": "propose_schedule", "arguments": {}}], "tool_call_id": null,
  "action_id": null, "run_id": null,
  "stats": {"prompt_tokens": 900, "cached_tokens": 600, "processed_tokens": 300, "completion_tokens": 80,
            "llm_seconds": 9.2, "decode_tps": 9.1, "prefill_tps": 85.0, "think": false},
  "created_at": 0 }
```
- `GET /api/conversations` → `[{"id","title","updated_at","message_count"}]`; `POST /api/conversations` body `{"title": null}` → conversation; `GET /api/conversations/{id}` → `{"id","title","messages": Message[]}`; `DELETE`; `PUT` body `{"title"}` to rename.
- `POST /api/uploads` → `{id, mime, size, name, kind, url, ...}`. Upload an image (PNG/JPEG/GIF/WebP, max 12 MB) or a document (PDF, Word `.docx`, Excel `.xlsx`, CSV/TSV, Markdown `.md`/`.markdown`, plain `.txt`, max 25 MB; no legacy `.doc`/`.xls`). Either JSON `{"data_url": "data:<type>;base64,...", "name": "x.png"}` or the raw file as the body with `?name=report.pdf` (preferred for documents). The type is sniffed from the bytes (text, CSV and TSV need a matching extension; PDF, DOCX and XLSX are detected from their content); `kind` is `"image"` or `"document"`; documents also report `chars`, `pages` (PDF), `rows` (CSV/TSV data rows; non-empty rows over all sheets for XLSX), `sheets` (XLSX), `scanned` (PDF with no text layer) and `truncated`. 422 for unsupported, empty, corrupt or password-protected files. `GET /api/uploads/{id}` returns the file; `GET /api/uploads/{id}/info` its metadata. Upload first, then pass the ids as `images` (max 6, images and documents mixed) to a chat message, agent run or schedule. Document text is extracted once at upload time and inlined into the prompt (about 24,000 characters per message in total; longer ones are truncated and the chat assistant can page through the rest with its `read_document` tool). A scanned PDF is shown to the model as page images (first 4 pages) and, like images, needs a vision projector. `GET /api/status` has `llm.vision` (true when llama-server runs with `--mmproj`).
- `POST /api/conversations/{id}/messages` body `{"content": "...", "thinking": false, "effort": "low", "mode": "auto", "images": ["<upload id>"]}` (`mode` = `auto` | `manual` | `plan`, default from setting `chat_mode`; `manual` emits `approval_required {id,name,arguments}` for `run_command`/`run_agent` and waits for `POST /api/chat/approvals/{id}` body `{"approve": bool}` (10 min timeout = deny, then `approval_resolved`); `plan` is read-only: no agent runs or proposals, only simple read-only shell commands; `content` may be empty when images are given; messages carry `images: [ids]`) → **SSE** stream (the response itself):
  - `message_start` `{message_id}`
  - `token` `{channel: "content"|"reasoning", text}`
  - `tool_call` `{id, name, arguments}`  /  `tool_result` `{id, name, ok, result}`
  - `action_proposed` `{action: PendingAction}` (UI renders an Approve / Reject card)
  - `run_started` `{run_id}` (assistant started a web agent run; UI links to `/runs/{run_id}`)
  - `llm_end` `{prompt_tokens, cached_tokens, processed_tokens, completion_tokens, llm_seconds, prefill_tps, decode_tps}`
  - `message_end` `{message: Message}`  (a turn may contain several llm calls / messages when tools are used)
  - `done` `{}`  /  `error` `{detail}`
  Closing the connection (AbortController) cancels generation.

### GET /api/conversations/{id}/context?effort=&thinking=
Context ring data: `limit`, `reserve`, `budget`, `used` and the share used (see `docs/CONTEXT.md`).

### POST /api/conversations/{id}/compact   body `{"thinking": bool?, "effort": str?}`
Compact now: prune old tool output and fold older messages into the rolling summary. The transcript is not changed.

## Stats

### GET /api/stats/summary?days=7
```json
{ "days": 7,
  "runs": {"total": 40, "done": 33, "failed": 3, "budget": 2, "stopped": 2, "success_rate": 0.82},
  "tokens": {"input": 410000, "cached": 360000, "processed": 50000, "output": 21000, "cache_hit_rate": 0.88},
  "timing": {"avg_wall_s": 58.2, "avg_llm_s_per_step": 4.1, "avg_decode_tps": 9.4, "avg_prefill_tps": 88.0},
  "by_day": [{"day": "2026-11-06", "runs": 7, "input": 1, "cached": 1, "output": 1, "llm_seconds": 1.0}],
  "by_agent": [{"agent_id": "a1", "agent_name": "News watcher", "runs": 5, "success_rate": 1.0, "input": 1, "output": 1, "avg_wall_s": 40.0}],
  "slowest_runs": [RunSummary] }
```

## Frontend expectations (pages)
Overview (status cards, running runs, upcoming schedules, recent runs, quick-ask box) · Chat · Agents (list + editor + "Run now")
· Schedules (table, create/edit form with cron presets and live preview, "Ask the assistant" shortcut) · Runs (filterable list)
· Run detail (LIVE: streaming reasoning/content, current tool, step timeline with tokens/timing, latest screenshot, stop button)
· Memory · Skills · Stats (charts: tokens/day, runs/day, timing) · Settings (schema-driven) · Approvals (badge in the nav).

# Version history

Newest first. The running version is shown at the bottom of the dashboard sidebar and in `GET /api/status`.

| Version | Date | Highlights |
|---|---|---|
| 0.8.1 | 2026-11-10 | **Fixes**: leaving the Chat page no longer stops a running reply (only Stop does); the sidebar model light no longer flickers red on a single missed health probe (down is reported after 3 consecutive misses). |
| 0.8.0 | 2026-11-10 | **Per-agent state**: agents get a `set_state` tool (no approval, max 2000 chars) to leave a private note for their next run ("last status", "checked up to X"); it is injected at the top of every run and is viewable/editable/clearable in the agent's edit dialog. API: `GET/PUT/DELETE /api/agents/{id}/state`. Always available even when an agent's tool list is restricted. |
| 0.7.0 | 2026-11-10 | **`update_memory` agent tool**: a job can replace its own saved memory (e.g. a single "last status") by id instead of adding a near-duplicate every run; `remember` skips exact duplicates; memory ids are shown in the injected memories and in `recall`. **Agent memory scope now defaults to `agent`** everywhere (new agents, default agent, run config, DB schema). New approval kind `update_memory`. |
| 0.6.0 | 2026-11-10 | **Artifact previews in chat**: images the assistant creates or mentions appear as inline thumbnails under the reply (click for full size); PDFs, text, Markdown, JSON and CSV files appear as expandable preview cards. |
| 0.5.2 | 2026-11-10 | **Stale UI fix**: the page (`index.html`) is now served with `Cache-Control: no-cache` and hashed assets as immutable, so a browser can no longer keep an old build (missing Copy / Run again / timestamps) after an update. |
| 0.5.1 | 2026-11-10 | **Model switcher can stop servers started from a terminal** (ops/start.sh or by hand): Atom finds the llama-server on the profile's port and stops it, so every running model shows a Stop button. |
| 0.5.0 | 2026-11-10 | **Uncensored model profile**: huihui-ai abliterated Qwen3.8-27B (Q4_K, :8082) selectable in the model switcher, per agent, and via `ops/llama-server.sh uncensored`. |
| 0.4.0 | 2026-11-10 | **Chat page**: every message shows its date and time; **Copy** on user and assistant messages; **Run again** re-sends the prompt a reply answered. Images page also shows date/time. |
| 0.3.0 | 2026-11-10 | Images page: **Copy prompt**, **Run again** (same settings, new random seed), **Retry** on failures, "Reuse settings" renamed **Edit in box**. LUSTIFY V10 (Krea 2) service and image-to-image. |
| 0.2.0 | 2026-11-09 | SDXL image service, Images page, sandboxed file tools, clickable file paths in chat, Z-Image generate_image tool. |

# Atom

A local web-agent platform: a real browser (Playwright) driven by a local Qwen3.8-27B (4-bit GGUF on llama.cpp),
with scheduled tasks, a chat assistant, memory, skills and a live dashboard. Built for an M1 Max 64 GB.

## Run

```sh
ops/start.sh                      # model server (:8080) + dashboard backend (:8787); Ctrl+C stops both
open http://127.0.0.1:8787        # the dashboard
```

Pieces separately: `ops/llama-server.sh` (3 slots: agent / extraction+thinking / chat) and `uv run python -m atom serve`.

## Use

- **Dashboard** (`web/`, React): Overview, Chat, Agents, Schedules, Runs (live view), Memory, Skills, Stats, Settings, Approvals.
- **CLI**: `uv run python -m atom run "task" --url https://example.com [--agent NAME] [--thinking off|auto|on]`,
  `atom runs`, `atom show <run_id>`, `atom llm-check`.
- **Evals**: `uv run python -m evals.run_evals --suite all [--repeat N]` (5 local fixture tasks + 2 live).
- **Tests**: `uv run pytest` (no model needed; uses a scripted fake LLM and a local fixture site).
- **Frontend dev**: `cd web && pnpm install && pnpm dev` (proxies /api to :8787); `pnpm build` writes `web/dist`.

## MCP connectors

Agents can use tools from MCP servers. Put them in `data/mcp.json` (standard `mcpServers` format; stdio via
`command`/`args`/`env`, or remote via `url`/`headers`; `"disabled": true` skips one), then restart or
`POST /api/mcp/reload`. Status: `GET /api/mcp`. Tools appear as `mcp_<server>_<tool>` in `/api/tools` and agent
tool pickers; results are wrapped as untrusted data. Tools without a read-only hint are flagged `side_effect`.

## Layout

```
atom/            backend: agent loop, browser layer, tools, scheduler, stores, assistant, FastAPI app
  browser/       Playwright session, compact snapshots, readable text
  server/        REST + SSE API (contract: docs/DASHBOARD_API.md)
web/             dashboard frontend
evals/           eval tasks, local fixture site, results
ops/             start scripts
data/            SQLite db, run traces + screenshots, skills (SKILL.md files)   (gitignored)
```

## Notes

- Prefill is the slow part on this hardware (~100-125 tok/s) and decode is ~13 tok/s. The agent keeps history
  append-only so llama-server's prompt cache is reused (steps typically re-read only 100-300 new tokens).
  Thinking mode always breaks the cache for that call, so it is off by default and `auto` only uses it to recover.
- Anything the assistant or an agent wants to persist (schedules, agents, skills, memories) is a pending action
  you approve in the UI, unless "Auto-approve assistant actions" is on in Settings.
- Page text and tool results are treated as untrusted data; navigation is checked against per-agent domain allowlists
  and private-network addresses are blocked unless an agent explicitly allows them.

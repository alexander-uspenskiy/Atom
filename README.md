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

## Environment & secret variables

Settings → "Environment & secrets" stores named values (`/api/variables`, SQLite, plain text, local only). Agents use
them by writing `{{NAME}}` inside a tool argument; the value is filled in when the tool runs. Plain variables are listed
(with values) in the agent's prompt. Secrets are never shown to the model or the API: they work only with `type`,
`select_option`, `open_url` and `mcp_*` tools, can be limited to domains, and are scrubbed from tool output and run logs.

## Connectors

Settings → Connectors adds first-party integrations (`/api/connectors`). Currently **Gmail** (IMAP/SMTP): tools
`gmail_<name>_search` (Gmail search syntax), `gmail_<name>_read`, and `gmail_<name>_send` only when "Allow agents to
send email" is on (off by default, since email content is untrusted input). Several accounts can be connected.

**Sign in with Google (recommended):** in Google Cloud Console create an OAuth client of type *Desktop app* (consent
screen: add yourself as a test user, or publish it as "In production" for personal use, otherwise Google expires the
token after 7 days). Enable IMAP in Gmail. Save the client ID/secret on the connector and click *Sign in*; the browser
completes the OAuth flow (PKCE, loopback redirect to the dashboard's own address) and no password is stored. Alternative:
a Google app password. All connector secrets (client secret, app password, refresh token) are kept in the system
keychain, never in the database.

**Telegram** (chat with Atom from your phone): in Telegram message @BotFather, send `/newbot`, name it "Atom" and pick a
username ending in `bot`. In Settings → Connectors add a Telegram connector with the token (kept in the keychain). The bot
long-polls Telegram, so nothing is exposed to the internet. Only user IDs listed under "Allowed user IDs" can use it:
save it empty, message the bot once, and it replies with your ID; then add the ID. Messages go to the dashboard assistant
(one conversation per user, visible on the Chat page; `/new` starts a fresh one). Proposals (schedules, agents, ...) arrive
with Approve / Reject buttons. Send a photo or a document (PDF, Word, Excel, CSV, Markdown, text file), optionally with a caption, and the assistant reads it, same as a file attached in the dashboard chat. Ask it to show you a run's screenshot and it sends the picture back. Agents can attach a page screenshot to `telegram_<name>_send` (`include_screenshot`). "Forwarding recipients" lists Telegram user IDs (each must press Start in the bot once) that a job may copy its message to: only when the job's instruction says e.g. "forward to 987654321", and only IDs on that list; a failed copy never fails the run. With "Let agents message me" on, agents get `telegram_<name>_send` to notify you from
scheduled runs. Private chats only.

To add a connector type, subclass `Connector` in `atom/connectors/`, declare its `fields` (and `oauth` if it signs in
through the browser) and `build_tools`, and `register()` it; the UI form is generated from the field schema. Connectors that listen for events (like Telegram) set
`background = True` and implement `run(name, cfg, svc)`; the manager runs it while the connector is enabled and restarts it on config changes.

## MCP servers

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
data/            SQLite db, run traces + screenshots   (gitignored)
~/.atom/skills/  user-level skills (SKILL.md folders); a project folder adds <folder>/.atom/skills or <folder>/.agents/skills
```

## Notes

- Prefill is the slow part on this hardware (~100-125 tok/s) and decode is ~13 tok/s. The agent keeps history
  append-only so llama-server's prompt cache is reused (steps typically re-read only 100-300 new tokens).
  Thinking mode always breaks the cache for that call, so it is off by default and `auto` only uses it to recover.
- Anything the assistant or an agent wants to persist (schedules, agents, skills, memories) is a pending action
  you approve in the UI, unless "Auto-approve assistant actions" is on in Settings.
- Page text and tool results are treated as untrusted data; navigation is checked against per-agent domain allowlists
  and private-network addresses are blocked unless an agent explicitly allows them.

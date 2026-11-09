# Chat context: limit calculation and summarising strategy

## 1. How the limit is calculated (implemented: `Assistant.context_usage`, `GET /api/conversations/{id}/context`)

llama-server splits `-c` across slots: `ATOM_CTX_TOTAL=98304`, `-np 3` -> **32 768 tokens per slot**. Chat runs on
slot 2 (`chat_slot`), so that is the hard ceiling for a chat.

| Quantity | Source |
|---|---|
| `limit` | `n_ctx` of the chat slot from llama-server `/slots` (authoritative); falls back to setting `ctx_per_slot` |
| `reserve` | the reply budget (`max_tokens`): 1500 non-thinking; 3000 / 5000 / 8000 for thinking low / medium / xhigh. It must fit in the same window |
| `budget` | `limit - reserve` = the most prompt we can send safely (~31 k non-thinking, ~24 k at xhigh) |
| `used` | exact: newest call's `prompt_tokens + completion_tokens` (server count, includes system prompt, tools, skills, pinned memories, images) **plus** a chars/4 estimate for messages added since (tool results, the unsent turn). Before any call: chars/4 over the rebuilt prompt |
| ring % | `used / budget` (amber >= 70 %, red >= 90 %) |

Why not tokenise locally: the model's tokenizer isn't available in Python, while llama-server already reports exact
counts on every call, so only the small tail is estimated.

Before compaction existed, `_history` kept the newest **40 messages** and silently drops the rest, so
long chats lose their beginning (decisions, user preferences, file paths) without warning, and 40 messages with big
tool outputs can still overflow the slot.

## 2. Summarising strategy (implemented: `Assistant.compact`, setting `chat_compact_at`, `POST /api/conversations/{id}/compact`)

Goals: never overflow, keep the llama-server prefix cache warm as long as possible, keep what matters.

**Trigger.** After a turn, if `used / budget >= 0.75` (new setting `chat_compact_at`, default 0.75), compact before
the *next* turn. Hard guard: if the rebuilt prompt would exceed `budget`, compact first, synchronously.

**What is compacted (tiered, cheapest first):**
1. *Prune tool output* (no model call): replace old tool results (all but the newest 2 turns) with
   `[tool result omitted: <name>, <n> chars]`; keep the tool call itself. Terminal/read_text results are the usual bloat.
2. *Drop old images*: already done (`MAX_HISTORY_IMAGE_MESSAGES`).
3. *Summarise the head*: keep the newest ~25 % of the budget verbatim (always whole turns: user -> assistant -> tools,
   never splitting a tool call from its result); summarise everything older into one rolling summary.

**Summary.** One non-thinking call on the chat slot (`max_tokens` ~700), prompt = previous summary + the messages
being folded in, asking for fixed sections: *User goals & preferences / Decisions made / Facts, names, paths, IDs /
Work done & results / Open questions & next steps*. Rolling: each pass folds the old summary and new head into a new
one, so size stays bounded (~700 tokens) instead of growing.

**Storage (non-destructive).** New table `conversation_summaries(conversation_id, upto_seq, text, created_at)`.
Messages are never deleted, so the UI still shows the full transcript. `_history` becomes:
`system + "[Summary of earlier conversation]\n" + text` as one user message, then messages with `seq > upto_seq`.
This replaces the blunt `[-40:]` cut. The UI shows a divider "Earlier messages summarised" at `upto_seq`, and the ring
drops.

**Cache cost.** Compaction rewrites the prefix once (one full re-prefill of ~25 k tokens, likely 30-60 s on the
M1 Max; not measured), then the prefix is stable again. Triggering at 75 % and compacting down to ~35 % buys many cheap
turns between compactions. Run it right after the reply streams (while the user reads), not before the next send.

**Edge cases.** Thinking mode lowers the budget (bigger reserve): compute the trigger from the current effort.
Summary failure -> fall back to tier-1 pruning plus the 40-message cut. Pinned memories are already in the system
prompt, so they are not summarised. A manual "Compact now" button on the ring is a later extra.

**Rollout.** (1) tier-1 pruning + replace `[-40:]` with a token-budgeted window (small, safe, no model call);
(2) rolling summary + table + UI divider; (3) setting + manual button. The agent loop already has its own
`_compact` (action log), unrelated and unchanged.

### As built
- Trigger: after each reply when `used/budget >= chat_compact_at` (Settings, default 0.75), plus a guard before every
  model call at 0.95. Clicking the ring compacts on demand. A failed summary never breaks the turn: old tool output is
  still dropped and the 40-message cap remains the fallback.
- State lives in `conversation_summaries` (one rolling row per chat): `upto_seq` (messages folded into `text`),
  `pruned_upto` (tool results elided in the prompt), `at_seq` (so the ring ignores server counts older than the last
  compaction). The summary goes into the system prompt; the transcript in the UI is untouched and shows a divider.
- Not done: summary quality has not been tried on the real model, and the ~30-60 s re-prefill cost is still an estimate.

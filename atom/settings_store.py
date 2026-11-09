"""Runtime-editable settings: defaults come from config.Settings, overrides live in the DB."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import LLM_PROFILES, Settings, profile_target
from .db import Database, jdump, jload

TZ_HELP = "IANA timezone used for schedules created by the assistant, e.g. America/New_York."

SCHEMA: list[dict[str, Any]] = [
    # --- Model ---
    {"key": "llm_profile", "label": "Model", "group": "Model", "type": "select", "options": list(LLM_PROFILES),
     "help": "qwen = Qwen3.8-27B (:8080). arete = NousResearch Arete-27B 4-bit (:8081). Sets the URL and model name "
             "below; start the matching server with ops/llama-server.sh <profile>."},
    {"key": "llm_base_url", "label": "LLM server URL", "group": "Model", "type": "text",
     "help": "OpenAI-compatible endpoint (llama-server). Changing this reconnects immediately."},
    {"key": "llm_model", "label": "Model name", "group": "Model", "type": "text",
     "help": "Alias the server exposes (llama-server --alias)."},
    {"key": "temperature", "label": "Temperature", "group": "Model", "type": "slider", "min": 0, "max": 1.5, "step": 0.05,
     "help": "Used when thinking is off. Thinking mode always uses the model card's 1.0."},
    {"key": "top_p", "label": "Top-p", "group": "Model", "type": "slider", "min": 0.1, "max": 1, "step": 0.01},
    {"key": "top_k", "label": "Top-k", "group": "Model", "type": "number", "min": 0, "max": 200, "step": 1},
    {"key": "presence_penalty", "label": "Presence penalty", "group": "Model", "type": "slider", "min": 0, "max": 2,
     "step": 0.1, "help": "Keep at 0 for tool calls; higher values can corrupt exact refs and arguments."},
    # --- Thinking ---
    {"key": "agent_thinking", "label": "Agent thinking", "group": "Thinking", "type": "select",
     "options": ["off", "auto", "on"],
     "help": "off = never. auto = off, escalate to thinking when stuck. on = always think: far slower, and thinking "
             "breaks the prompt cache when mixed with non-thinking steps."},
    {"key": "agent_effort", "label": "Agent reasoning effort", "group": "Thinking", "type": "select",
     "options": ["low", "medium", "xhigh"], "help": "How long the model thinks when thinking is used. xhigh can be very slow."},
    {"key": "chat_thinking", "label": "Chat thinking", "group": "Thinking", "type": "boolean",
     "help": "Default for new chat messages; can be toggled per message."},
    {"key": "chat_effort", "label": "Chat reasoning effort", "group": "Thinking", "type": "select",
     "options": ["low", "medium", "xhigh"]},
    # --- Agent limits ---
    {"key": "max_steps", "label": "Max steps per run", "group": "Agent limits", "type": "number", "min": 1, "max": 400, "step": 1},
    {"key": "max_wall_s", "label": "Max seconds per run", "group": "Agent limits", "type": "number", "min": 30, "max": 7200, "step": 30},
    {"key": "compact_at_tokens", "label": "Compact history at (tokens)", "group": "Agent limits", "type": "number",
     "min": 4000, "max": 30000, "step": 500,
     "help": "When the prompt grows past this, history is summarised (one slow re-read of the prompt)."},
    {"key": "chat_compact_at", "label": "Summarise chats at (context %)", "group": "Agent limits", "type": "slider",
     "min": 0.3, "max": 0.95, "step": 0.05,
     "help": "When a chat fills this share of its context budget, old tool output is dropped and older messages are "
             "folded into a summary (one slow re-read of the prompt). The ring in the chat shows the current share."},
    {"key": "max_observation_tokens", "label": "Max observation tokens", "group": "Agent limits", "type": "number",
     "min": 300, "max": 6000, "step": 100, "help": "Cap on what each action returns to the model. Prefill is slow, keep small."},
    {"key": "max_read_tokens", "label": "read_text chunk (tokens)", "group": "Agent limits", "type": "number",
     "min": 500, "max": 8000, "step": 250},
    {"key": "max_concurrent_runs", "label": "Concurrent runs", "group": "Agent limits", "type": "number",
     "min": 1, "max": 3, "step": 1, "help": "Runs share one model; more than 1 slows each of them and shares a cache slot."},
    # --- Browser ---
    {"key": "headless", "label": "Headless browser", "group": "Browser", "type": "boolean",
     "help": "Turn off to watch the browser window while runs execute."},
    {"key": "live_screenshots", "label": "Live screenshots", "group": "Browser", "type": "boolean",
     "help": "Capture a small JPEG after each action for the live run view (~0.2 s each)."},
    {"key": "agent_vision", "label": "Agents can look at pages", "group": "Browser", "type": "boolean",
     "help": "Adds a `look` tool that shows the model a screenshot of the page (needs the vision projector). "
             "Page images are loaded for those runs, and each screenshot costs about 1-2k prompt tokens."},
    # --- Terminal ---
    {"key": "terminal_enabled", "label": "Enable terminal", "group": "Terminal", "type": "boolean",
     "help": "Lets the chat assistant (run_command) and agents that have the `terminal` tool selected run shell "
             "commands as your user. Agents never get it from 'All tools'. Agents read untrusted web pages, so "
             "only enable this on a machine you trust."},
    {"key": "terminal_dir", "label": "Terminal working folder", "group": "Terminal", "type": "folder",
     "help": "Where commands start (chat, and agents without their own folder). Empty = data/workspace inside Atom."},
    {"key": "terminal_timeout_s", "label": "Terminal timeout (s)", "group": "Terminal", "type": "number",
     "min": 1, "max": 300, "step": 5, "help": "Default per-command time limit; commands are killed after it."},
    {"key": "terminal_restrict", "label": "Restrict terminal to project folder", "group": "Terminal", "type": "boolean",
     "help": "Guardrail (recommended). Commands must run inside the project folder, and commands that reference "
             "paths outside it (absolute paths, ~, ..) are refused. This is a best-effort check, not a sandbox: "
             "a determined script can still get around it."},
    # --- Assistant & memory ---
    {"key": "chat_mode", "label": "Default chat mode", "group": "Assistant & memory", "type": "select",
     "options": ["auto", "manual", "plan"],
     "help": "Auto: the assistant runs commands and agents on its own. Manual: you approve every command and run "
             "first, and proposals are never auto-approved. Plan: read-only; it can inspect and propose a plan but "
             "cannot change anything. The chat box can override this per message."},
    {"key": "auto_approve_assistant_actions", "label": "Auto-approve assistant actions", "group": "Assistant & memory",
     "type": "boolean", "help": "OFF (recommended): the assistant only proposes schedules, agents, skills and memories; "
                                "you approve them. ON: they are created immediately."},
    {"key": "memory_inject_k", "label": "Memories injected per run", "group": "Assistant & memory", "type": "number",
     "min": 0, "max": 12, "step": 1, "help": "Top relevant memories added to each run's first message (pinned ones always are)."},
    {"key": "timezone", "label": "Timezone", "group": "Assistant & memory", "type": "text", "help": TZ_HELP},
]
KEYS = {s["key"] for s in SCHEMA}
SELECTS = {s["key"]: s["options"] for s in SCHEMA if s["type"] == "select"}


class SettingsError(ValueError):
    pass


def _coerce(spec: dict, value: Any) -> Any:
    t = spec["type"]
    if t == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).lower() in ("false", "0", "no", "off"):
            return False
        raise SettingsError(f"{spec['key']}: expected boolean")
    if t in ("number", "slider"):
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{spec['key']}: expected a number") from None
        if "min" in spec and num < spec["min"] or "max" in spec and num > spec["max"]:
            raise SettingsError(f"{spec['key']}: must be between {spec.get('min')} and {spec.get('max')}")
        return int(num) if spec.get("step", 0) >= 1 and float(spec["step"]).is_integer() else num
    if t == "select":
        if value not in spec["options"]:
            raise SettingsError(f"{spec['key']}: must be one of {spec['options']}")
        return value
    if t == "folder":
        v = str(value or "").strip()
        if v and not Path(v).expanduser().is_dir():
            raise SettingsError(f"{spec['key']}: '{v}' is not an existing folder")
        return v
    return str(value).strip()


class SettingsStore:
    def __init__(self, db: Database, base: Settings | None = None):
        self.db = db
        self.base = base or Settings()
        self._effective: Settings | None = None
        self._listeners: list = []

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def overrides(self) -> dict[str, Any]:
        return {r["key"]: jload(r["value"]) for r in self.db.all("SELECT key, value FROM settings")}

    def effective(self) -> Settings:
        if self._effective is None:
            ov = {k: v for k, v in self.overrides().items() if k in KEYS}
            self._effective = self.base.model_copy(update=ov)
        return self._effective

    def defaults(self) -> dict[str, Any]:
        return {k: getattr(self.base, k) for k in KEYS}

    def values(self) -> dict[str, Any]:
        eff = self.effective()
        return {k: getattr(eff, k) for k in KEYS}

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        specs = {s["key"]: s for s in SCHEMA}
        unknown = [k for k in values if k not in specs]
        if unknown:
            raise SettingsError(f"unknown setting(s): {', '.join(unknown)}")
        clean = {k: _coerce(specs[k], v) for k, v in values.items()}
        if "timezone" in clean:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(clean["timezone"])
            except Exception:  # noqa: BLE001
                raise SettingsError(f"timezone: unknown timezone '{clean['timezone']}'") from None
        if "llm_profile" in clean:  # a profile choice sets the server URL and model name together
            clean["llm_base_url"], clean["llm_model"] = profile_target(clean["llm_profile"])
        for k, v in clean.items():
            self.db.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, jdump(v)))
        self._effective = None
        for fn in self._listeners:
            fn(self.effective(), set(clean))
        return self.values()

    def payload(self) -> dict[str, Any]:
        return {"values": self.values(), "defaults": self.defaults(), "schema": SCHEMA}

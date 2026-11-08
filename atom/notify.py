"""RunNotifier: when a run that was started from chat finishes, post its result back into that conversation.

The chat assistant cannot wait for slow runs (a turn ends when it replies), so this closes the loop: it listens to the
global event feed, finds the conversation that started the run, appends the outcome as an assistant message, and
pushes it to live sinks (e.g. the Telegram bridge) so the user hears about it without asking again.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger("atom.notify")

Sink = Callable[[str, str], Awaitable[None]]          # (conversation title, text) -> None
MAX_RESULT = 3500


def _clip(s: str, n: int = MAX_RESULT) -> str:
    return s if len(s) <= n else s[:n].rstrip() + "…"


def format_outcome(run: dict) -> str:
    """Plain-text report for a finished run."""
    name = run.get("agent_name") or "Agent"
    head = f"Run {run['id']} ({name}) "
    status = run.get("status")
    secs = run.get("wall_seconds")
    took = f" after {int(secs // 60)} min {int(secs % 60)} s" if secs else ""
    if status == "done" and run.get("success"):
        result = run.get("result")
        body = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1) if result else ""
        return f"{head}finished{took}.\n\n{_clip(body.strip()) or '(no result text)'}"
    if status == "stopped":
        return f"{head}was stopped{took}."
    why = run.get("error") or (run.get("result") if isinstance(run.get("result"), str) else "") or "no details"
    return f"{head}{'failed' if status == 'failed' else 'ended without success'}{took}.\n\n{_clip(str(why).strip(), 800)}"


class RunNotifier:
    def __init__(self, svc: Any):
        self.svc = svc
        self.sinks: dict[str, Sink] = {}
        self._task: asyncio.Task | None = None

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        t, self._task = self._task, None
        if t:
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)

    def add_sink(self, key: str, fn: Sink) -> None:
        self.sinks[key] = fn

    def remove_sink(self, key: str, fn: Sink | None = None) -> None:
        if fn is None or self.sinks.get(key) == fn:
            self.sinks.pop(key, None)

    # ---------- handling ----------
    async def _loop(self) -> None:
        async for ev in self.svc.bus.stream_global():
            if ev.get("type") != "run_finished":
                continue
            try:
                await self.handle(ev["run"])
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("run notification failed")

    def _conversation(self, run_id: str) -> str | None:
        r = self.svc.db.one("SELECT conversation_id FROM messages WHERE run_id=? AND role='tool' ORDER BY rowid LIMIT 1",
                            (run_id,))
        return r["conversation_id"] if r else None

    def _already_reported(self, conv_id: str, run_id: str) -> bool:
        """True if a get_run call in this conversation already returned the finished run to the model."""
        for m in self.svc.conversations.get(conv_id)["messages"]:
            if m["role"] != "tool" or run_id not in (m["content"] or ""):
                continue
            try:
                d = json.loads(m["content"])
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("id") == run_id and d.get("status") not in ("queued", "running"):
                return True
        return False

    async def handle(self, run: dict) -> bool:
        if run.get("trigger") != "chat":
            return False
        conv_id = self._conversation(run["id"])
        if not conv_id or not self.svc.conversations.exists(conv_id) or self._already_reported(conv_id, run["id"]):
            return False
        run = self.svc.runs.get(run["id"])                      # the event row can predate the final result
        text = format_outcome(run)
        self.svc.conversations.append(conv_id, "assistant", text, run_id=run["id"])
        self.svc.bus.publish_global("chat_message", conversation_id=conv_id, run_id=run["id"])
        title = self.svc.conversations.get(conv_id)["title"] or ""
        for fn in list(self.sinks.values()):
            try:
                await fn(title, text)
            except Exception:  # noqa: BLE001
                log.exception("notification sink failed")
        return True

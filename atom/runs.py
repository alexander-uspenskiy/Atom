"""RunManager: resolves run configuration, queues runs, executes them, supports stop."""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .agent import Agent, RunConfig, RunResult
from .events import EventBus
from .settings_store import SettingsStore
from .stores import Conflict, NotFound, RunStore, ScheduleStore


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


class RunManager:
    def __init__(self, settings: SettingsStore, runs: RunStore, schedules: ScheduleStore, agent: Agent, bus: EventBus):
        self.settings, self.runs, self.schedules, self.agent, self.bus = settings, runs, schedules, agent, bus
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._cfg: dict[str, tuple[str, RunConfig]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._workers: list[asyncio.Task] = []

    # ---------- configuration ----------
    def resolve(self, agent: dict, *, start_url: str | None = None, overrides: dict | None = None,
                trigger: str = "manual", schedule_id: str | None = None) -> RunConfig:
        s = self.settings.effective()
        ov = overrides or {}
        thinking = ov.get("thinking") or (agent["thinking"] if agent["thinking"] != "inherit" else s.agent_thinking)
        effort = ov.get("effort") or (agent["effort"] if agent["effort"] != "inherit" else s.agent_effort)
        if thinking == "inherit":
            thinking = s.agent_thinking
        if effort == "inherit":
            effort = s.agent_effort
        profile = (s.data_dir / "profiles" / agent["profile"]) if agent.get("profile") else None
        return RunConfig(
            agent=agent, start_url=start_url or agent.get("start_url"),
            allowed_domains=agent["allowed_domains"] or None, allow_private=agent["allow_private"],
            max_steps=int(ov.get("max_steps") or agent.get("max_steps") or s.max_steps), thinking=thinking,
            effort=effort, temperature=agent.get("temperature"), profile=profile, tool_names=agent["tools"],
            skill_names=list(agent["skills"]), memory_scope=agent["memory_scope"], trigger=trigger,
            schedule_id=schedule_id)

    def _create_row(self, task: str, cfg: RunConfig) -> dict:
        s = self.settings.effective()
        run_id = new_run_id()
        row = self.runs.create(run_id, task, agent=cfg.agent, trigger=cfg.trigger, schedule_id=cfg.schedule_id,
                               config={"start_url": cfg.start_url, "allowed_domains": cfg.allowed_domains,
                                       "max_steps": cfg.max_steps, "thinking": cfg.thinking, "effort": cfg.effort,
                                       "images": cfg.images},
                               thinking=cfg.thinking, effort=cfg.effort, run_dir=str(s.runs_dir / run_id))
        self._cfg[run_id] = (task, cfg)
        return row

    # ---------- queueing ----------
    def enqueue(self, task: str, agent: dict, *, trigger: str = "manual", schedule_id: str | None = None,
                start_url: str | None = None, overrides: dict | None = None, images: list[str] | None = None) -> dict:
        cfg = self.resolve(agent, start_url=start_url, overrides=overrides, trigger=trigger, schedule_id=schedule_id)
        cfg.images = list(images or [])
        row = self._create_row(task, cfg)
        self.queue.put_nowait(row["id"])
        self.bus.publish_run(row["id"], "run_status", status="queued")
        self.bus.publish_global("run_queued", run=row)
        return row

    def running_ids(self) -> list[str]:
        return [rid for rid, t in self._tasks.items() if not t.done()]

    def queued_count(self) -> int:
        return sum(1 for rid in self._cfg if rid not in self._tasks and self.runs.get(rid)["status"] == "queued")

    async def start(self) -> None:
        n = self.runs.orphaned_to_failed()
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(3)]
        return None

    async def shutdown(self) -> None:
        for t in [*self._tasks.values(), *self._workers]:
            t.cancel()
        await asyncio.gather(*self._workers, *self._tasks.values(), return_exceptions=True)

    async def _worker(self, i: int) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                while len(self.running_ids()) >= self.settings.effective().max_concurrent_runs:
                    await asyncio.sleep(0.5)
                if run_id not in self._cfg or self.runs.get(run_id)["status"] != "queued":
                    continue
                await self._execute(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass

    async def _execute(self, run_id: str, console: Callable[[dict], None] | None = None) -> RunResult:
        task, cfg = self._cfg.pop(run_id)
        self.runs.mark_running(run_id)
        self.bus.publish_global("run_started", run=self.runs.get(run_id))
        prev_console = self.agent.console
        if console:
            self.agent.console = console
        t = asyncio.create_task(self.agent.run(run_id, task, cfg))
        self._tasks[run_id] = t
        try:
            result = await t
        except asyncio.CancelledError:
            if t.cancelled() or not t.done():
                t.cancel()
            raise
        finally:
            self._tasks.pop(run_id, None)
            self.agent.console = prev_console
        row = self.runs.get(run_id)
        if cfg.schedule_id:
            self.schedules.record_result(cfg.schedule_id, row["status"])
        self.bus.publish_global("run_finished", run=row)
        return result

    async def run_inline(self, task: str, agent: dict, *, start_url: str | None = None, overrides: dict | None = None,
                         trigger: str = "api", console: Callable[[dict], None] | None = None,
                         allowed_domains: list[str] | None = None, allow_private: bool | None = None) -> RunResult:
        """Run now without the queue (CLI and evals)."""
        cfg = self.resolve(agent, start_url=start_url, overrides=overrides, trigger=trigger)
        if allowed_domains is not None:
            cfg.allowed_domains = allowed_domains or None
        if allow_private is not None:
            cfg.allow_private = allow_private
        row = self._create_row(task, cfg)
        return await self._execute(row["id"], console)

    # ---------- stop ----------
    async def stop(self, run_id: str) -> dict:
        row = self.runs.get(run_id)
        if row["status"] == "queued":
            self._cfg.pop(run_id, None)
            self.runs.finish(run_id, "stopped", False, None, "stopped by user",
                             dict(steps=0, prompt_tokens=0, cached_tokens=0, processed_tokens=0, completion_tokens=0,
                                  llm_seconds=0, tool_seconds=0, wall_seconds=0))
            self.bus.publish_run(run_id, "run_finished", status="stopped", success=False, result=None,
                                 error="stopped by user", totals={})
            self.bus.publish_global("run_finished", run=self.runs.get(run_id))
        elif row["status"] == "running" and run_id in self._tasks:
            self._tasks[run_id].cancel()
            for _ in range(100):                     # wait for the agent to clean up and write its final row
                await asyncio.sleep(0.1)
                if self.runs.get(run_id)["status"] != "running":
                    break
        else:
            raise Conflict(f"run is already {row['status']}")
        return self.runs.get(run_id)      # the running case already published run_finished from _execute

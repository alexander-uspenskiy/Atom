"""Schedules: trigger validation/preview (cron, interval, once) and the APScheduler glue.

SQLite is the source of truth; APScheduler jobs are rebuilt from it at startup and on every change.
Policy for runs missed while the app was down: skipped (a fire within 5 minutes of its time is still honoured).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from cron_descriptor import get_description

from .events import EventBus
from .stores import AgentStore, Invalid, NotFound, ScheduleStore

log = logging.getLogger("atom.scheduler")
MIN_INTERVAL_S = 60


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        raise Invalid(f"unknown timezone '{name}'") from None


def normalize_trigger(trigger: dict, tz: str) -> dict:
    """Validate and return a clean trigger dict, or raise Invalid."""
    _tz(tz)
    t = (trigger or {}).get("type")
    if t == "cron":
        expr = " ".join(str(trigger.get("expr", "")).split())
        if len(expr.split()) != 5:
            raise Invalid("cron expression needs 5 fields: minute hour day-of-month month day-of-week")
        try:
            CronTrigger.from_crontab(expr, timezone=_tz(tz))
        except Exception as e:  # noqa: BLE001
            raise Invalid(f"invalid cron expression: {e}") from None
        return {"type": "cron", "expr": expr}
    if t == "interval":
        try:
            sec = int(trigger.get("seconds"))
        except (TypeError, ValueError):
            raise Invalid("interval needs an integer 'seconds'") from None
        if sec < MIN_INTERVAL_S:
            raise Invalid(f"interval must be at least {MIN_INTERVAL_S} seconds")
        return {"type": "interval", "seconds": sec}
    if t == "once":
        at = str(trigger.get("at", "")).strip()
        try:
            dt = datetime.fromisoformat(at)
        except ValueError:
            raise Invalid("once needs 'at' as an ISO datetime like 2026-11-07T08:00:00") from None
        return {"type": "once", "at": dt.replace(tzinfo=None).isoformat(timespec="seconds")}
    raise Invalid("trigger.type must be cron, interval or once")


def build_trigger(trigger: dict, tz: str):
    zone = _tz(tz)
    t = trigger["type"]
    if t == "cron":
        return CronTrigger.from_crontab(trigger["expr"], timezone=zone)
    if t == "interval":
        return IntervalTrigger(seconds=int(trigger["seconds"]), timezone=zone,
                               start_date=datetime.now(zone) + timedelta(seconds=int(trigger["seconds"])))
    return DateTrigger(run_date=datetime.fromisoformat(trigger["at"]).replace(tzinfo=zone), timezone=zone)


def describe(trigger: dict, tz: str) -> str:
    t = trigger["type"]
    if t == "cron":
        try:
            return get_description(trigger["expr"]) + f" ({tz})"
        except Exception:  # noqa: BLE001
            return f"cron {trigger['expr']} ({tz})"
    if t == "interval":
        s = int(trigger["seconds"])
        for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
            if s % n == 0:
                k = s // n
                return f"Every {unit}" if k == 1 else f"Every {k} {unit}s"
        return f"Every {s} seconds"
    return f"Once at {trigger['at'].replace('T', ' ')} ({tz})"


def preview(trigger: dict, tz: str, count: int = 5) -> list[str]:
    zone = _tz(tz)
    trig = build_trigger(trigger, tz)
    out: list[str] = []
    prev, now = None, datetime.now(zone)
    for _ in range(max(1, min(count, 20))):
        nxt = trig.get_next_fire_time(prev, prev or now)
        if nxt is None:
            break
        out.append(nxt.isoformat(timespec="seconds"))
        prev = nxt
        now = nxt
    return out


class SchedulerService:
    def __init__(self, schedules: ScheduleStore, agents: AgentStore, bus: EventBus, settings_fn):
        self.schedules, self.agents, self.bus, self.settings_fn = schedules, agents, bus, settings_fn
        self.runs = None          # set by Services (RunManager)
        self.sched: AsyncIOScheduler | None = None

    # ---------- lifecycle ----------
    def start(self) -> None:
        self.sched = AsyncIOScheduler(timezone="UTC")
        self.sched.start()
        for s in self.schedules.list():
            try:
                self.sync(s)
            except Exception as e:  # noqa: BLE001
                log.warning("could not schedule %s: %s", s["id"], e)

    def shutdown(self) -> None:
        if self.sched and self.sched.running:
            self.sched.shutdown(wait=False)

    def job_count(self) -> int:
        return len(self.sched.get_jobs()) if self.sched else 0

    # ---------- job sync ----------
    def sync(self, s: dict) -> None:
        assert self.sched is not None
        if self.sched.get_job(s["id"]):
            self.sched.remove_job(s["id"])
        if not s["enabled"]:
            self.schedules.set_next(s["id"], None)
            return
        trig = s["trigger"]
        if trig["type"] == "once" and datetime.fromisoformat(trig["at"]).replace(
                tzinfo=_tz(s["timezone"])) < datetime.now(_tz(s["timezone"])) - timedelta(minutes=5):
            self.schedules.update(s["id"], {"enabled": False})
            self.schedules.record_result(s["id"], "missed")
            self.schedules.set_next(s["id"], None)
            return
        job = self.sched.add_job(self._fire, build_trigger(trig, s["timezone"]), args=[s["id"]], id=s["id"],
                                 misfire_grace_time=300, coalesce=True, max_instances=1, replace_existing=True)
        nxt = job.next_run_time
        self.schedules.set_next(s["id"], nxt.timestamp() if nxt else None)

    def _refresh_next(self, sid: str) -> None:
        job = self.sched.get_job(sid) if self.sched else None
        nxt = job.next_run_time if job else None
        self.schedules.set_next(sid, nxt.timestamp() if nxt else None)

    async def _fire(self, sid: str) -> None:
        try:
            s = self.schedules.get(sid)
        except NotFound:
            return
        run = await self.trigger_now(sid, trigger="schedule")
        if s["trigger"]["type"] == "once":
            self.schedules.update(sid, {"enabled": False})
            self.schedules.set_next(sid, None)
        else:
            self._refresh_next(sid)
        self.bus.publish_global("schedule_fired", schedule_id=sid, run_id=run["id"])

    async def trigger_now(self, sid: str, trigger: str = "manual") -> dict:
        s = self.schedules.get(sid)
        agent = self.agents.get(s["agent_id"])
        run = self.runs.enqueue(s["task"], agent, trigger=trigger, schedule_id=sid, start_url=s["start_url"])
        self.schedules.record_fire(sid, run["id"])
        return run

    # ---------- validated CRUD used by the API and approvals ----------
    def _resolve_agent(self, ref: str | None) -> dict:
        if not ref:
            return self.agents.default()
        a = self.agents.find(ref)
        if not a:
            raise Invalid(f"agent '{ref}' not found")
        return a

    def create(self, d: dict) -> dict:
        tz = d.get("timezone") or self.settings_fn().timezone
        agent = self._resolve_agent(d.get("agent_id") or d.get("agent"))
        trigger = normalize_trigger(d.get("trigger") or {}, tz)
        s = self.schedules.create({**d, "agent_id": agent["id"], "trigger": trigger, "timezone": tz})
        self.sync(s)
        return self.schedules.get(s["id"])

    def update(self, sid: str, d: dict) -> dict:
        cur = self.schedules.get(sid)
        patch = {k: v for k, v in d.items() if k in ("name", "task", "start_url", "timezone", "enabled", "trigger", "agent_id", "agent")}
        if "agent" in patch:
            patch["agent_id"] = self._resolve_agent(patch.pop("agent"))["id"]
        elif "agent_id" in patch:
            patch["agent_id"] = self._resolve_agent(patch["agent_id"])["id"]
        tz = patch.get("timezone", cur["timezone"])
        if "trigger" in patch or "timezone" in patch:
            patch["trigger"] = normalize_trigger(patch.get("trigger", cur["trigger"]), tz)
        if "name" in patch and not str(patch["name"]).strip():
            raise Invalid("name is required")
        self.schedules.update(sid, patch)
        self.sync(self.schedules.get(sid))
        return self.schedules.get(sid)

    def delete(self, sid: str) -> None:
        self.schedules.delete(sid)
        if self.sched and self.sched.get_job(sid):
            self.sched.remove_job(sid)

    def toggle(self, sid: str, enabled: bool) -> dict:
        return self.update(sid, {"enabled": enabled})

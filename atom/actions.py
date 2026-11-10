"""Approvals: anything the assistant or an agent wants to persist (schedules, agents, skills, memories) becomes a
pending action that a human approves or rejects. Setting `auto_approve_assistant_actions` skips the wait."""
from __future__ import annotations

from typing import Any

from .events import EventBus
from .scheduler import SchedulerService, describe, normalize_trigger
from .settings_store import SettingsStore
from .skills import SkillStore
from .stores import ActionStore, AgentStore, Conflict, Invalid, MemoryStore, NotFound, ScheduleStore

KINDS = ("create_schedule", "create_agent", "create_skill", "save_memory", "update_memory", "update_schedule", "delete_schedule")


class ActionExecutor:
    def __init__(self, actions: ActionStore, agents: AgentStore, schedules: ScheduleStore, scheduler: SchedulerService,
                 skills: SkillStore, memory: MemoryStore, settings: SettingsStore, bus: EventBus):
        self.actions, self.agents, self.schedules, self.scheduler = actions, agents, schedules, scheduler
        self.skills, self.memory, self.settings, self.bus = skills, memory, settings, bus

    async def propose(self, kind: str, summary: str, payload: dict, *, created_by: str = "assistant",
                      conversation_id: str | None = None, run_id: str | None = None,
                      force_pending: bool = False) -> dict:
        if kind not in KINDS:
            raise Invalid(f"unknown action kind '{kind}'")
        self.validate(kind, payload)          # reject bad proposals up-front so the model can fix them
        action = self.actions.create(kind, summary, payload, created_by=created_by, conversation_id=conversation_id,
                                     run_id=run_id)
        if not force_pending and self.settings.effective().auto_approve_assistant_actions:
            return await self.approve(action["id"])
        self.bus.publish_global("action_pending", action=action)
        return action

    def validate(self, kind: str, p: dict) -> None:
        tz = p.get("timezone") or self.settings.effective().timezone
        if kind == "create_schedule":
            if not (p.get("name") or "").strip() or not (p.get("task") or "").strip():
                raise Invalid("schedule needs a name and a task")
            if p.get("agent") or p.get("agent_id"):
                if not self.agents.find(p.get("agent") or p.get("agent_id")):
                    raise Invalid(f"agent '{p.get('agent') or p.get('agent_id')}' not found; use list_agents")
            normalize_trigger(p.get("trigger") or {}, tz)
        elif kind == "create_agent":
            self.agents._clean(p)                    # validation only
        elif kind == "create_skill":
            if not (p.get("name") or "").strip() or not (p.get("body") or "").strip():
                raise Invalid("skill needs a name and a body")
        elif kind == "save_memory":
            if not (p.get("content") or "").strip():
                raise Invalid("memory needs content")
        elif kind == "update_memory":
            if not (p.get("content") or "").strip():
                raise Invalid("memory needs content")
            self.memory.get(str(p.get("id") or ""))      # NotFound if it is gone
        elif kind in ("update_schedule", "delete_schedule"):
            if not self.schedules.find(str(p.get("schedule") or "")):
                raise Invalid(f"schedule '{p.get('schedule')}' not found; use list_schedules")

    async def approve(self, aid: str, payload: dict | None = None) -> dict:
        action = self.actions.get(aid)
        if action["status"] != "pending":
            raise Conflict(f"action is already {action['status']}")
        final = payload if payload is not None else action["payload"]
        try:
            self.validate(action["kind"], final)
            result = self._run(action["kind"], final, action)
            decided = self.actions.decide(aid, "approved", result, final)
        except (Invalid, NotFound, Conflict, ValueError) as e:
            decided = self.actions.decide(aid, "failed", {"error": str(e)}, final)
        self.bus.publish_global("action_decided", action=decided)
        return decided

    async def reject(self, aid: str) -> dict:
        action = self.actions.get(aid)
        if action["status"] != "pending":
            raise Conflict(f"action is already {action['status']}")
        decided = self.actions.decide(aid, "rejected")
        self.bus.publish_global("action_decided", action=decided)
        return decided

    # ------------------------------------------------------------------
    def _run(self, kind: str, p: dict, action: dict) -> Any:
        by = action["created_by"] if action["created_by"] in ("assistant", "user") else "assistant"
        if kind == "create_schedule":
            s = self.scheduler.create({**p, "created_by": by})
            return {"schedule_id": s["id"], "name": s["name"], "next_run_at": s["next_run_at"],
                    "when": describe(s["trigger"], s["timezone"])}
        if kind == "create_agent":
            a = self.agents.create(p)
            return {"agent_id": a["id"], "name": a["name"]}
        if kind == "create_skill":
            s = self.skills.create({**p, "created_by": by})
            return {"skill": s["name"]}
        if kind == "save_memory":
            m = self.memory.create({**p, "status": "active", "source": p.get("source") or "assistant"})
            return {"memory_id": m["id"]}
        if kind == "update_memory":
            changes = {k: p[k] for k in ("title", "content", "tags") if k in p}
            m = self.memory.update(str(p["id"]), changes)
            return {"memory_id": m["id"]}
        if kind == "update_schedule":
            target = self.schedules.find(str(p["schedule"]))
            s = self.scheduler.update(target["id"], p.get("changes") or {})
            return {"schedule_id": s["id"], "next_run_at": s["next_run_at"]}
        if kind == "delete_schedule":
            target = self.schedules.find(str(p["schedule"]))
            self.scheduler.delete(target["id"])
            return {"deleted": target["id"]}
        raise Invalid(f"unknown action kind '{kind}'")

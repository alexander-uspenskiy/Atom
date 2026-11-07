"""Service container: wires stores, event bus, LLM client, agent runner, run manager, scheduler and approvals."""
from __future__ import annotations

from typing import Any

from .actions import ActionExecutor
from .agent import Agent
from .config import Settings
from .db import Database
from .events import EventBus
from .llm import LLM
from .mcp import McpManager
from .runs import RunManager
from .scheduler import SchedulerService
from .settings_store import SettingsStore
from .skills import SkillStore
from .stores import ActionStore, AgentStore, ConversationStore, MemoryStore, RunStore, ScheduleStore
from .tools import build_tools


class Services:
    def __init__(self, base_settings: Settings | None = None, *, llm: Any = None, db_path: str | None = None):
        base = base_settings or Settings()
        self.db = Database(db_path or base.db_path)
        self.settings = SettingsStore(self.db, base)
        eff = self.settings.effective()
        self.bus = EventBus(self.db)
        self.llm = llm or LLM(eff)
        self.tool_names = list(build_tools())          # mutated in place when MCP tools connect
        self.mcp = McpManager(eff.data_dir / "mcp.json")
        self.agents = AgentStore(self.db, self.tool_names)
        self.schedules = ScheduleStore(self.db)
        self.runs = RunStore(self.db)
        self.memory = MemoryStore(self.db)
        self.conversations = ConversationStore(self.db)
        self.action_store = ActionStore(self.db)
        self.skills = SkillStore(eff.skills_dir)
        self.scheduler = SchedulerService(self.schedules, self.agents, self.bus, self.settings.effective)
        self.executor = ActionExecutor(self.action_store, self.agents, self.schedules, self.scheduler, self.skills,
                                       self.memory, self.settings, self.bus)
        self.agent_runner = Agent(eff, self.llm, self.runs, self.bus, skills=self.skills, memory=self.memory,
                                  actions=self.executor)
        self.run_manager = RunManager(self.settings, self.runs, self.schedules, self.agent_runner, self.bus)
        self.scheduler.runs = self.run_manager
        self.settings.on_change(self._settings_changed)
        self.assistant = None            # set in server startup (needs the assistant module)

    def _settings_changed(self, eff: Settings, keys: set[str]) -> None:
        if hasattr(self.llm, "reconfigure"):
            self.llm.reconfigure(eff)
        self.agent_runner.update_settings(eff)

    async def refresh_mcp(self) -> None:
        await self.mcp.reload()
        base = list(build_tools())
        self.tool_names[:] = base + list(self.mcp.tools)
        self.agent_runner.all_tools = {**build_tools(), **self.mcp.tools}

    async def startup(self, *, scheduler: bool = True) -> None:
        self.agents.ensure_default()
        await self.refresh_mcp()
        await self.run_manager.start()
        if scheduler:
            self.scheduler.start()

    async def shutdown(self) -> None:
        self.scheduler.shutdown()
        await self.mcp.shutdown()
        await self.run_manager.shutdown()
        if hasattr(self.llm, "aclose"):
            await self.llm.aclose()
        self.db.close()

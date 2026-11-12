"""Service container: wires stores, event bus, LLM client, agent runner, run manager, scheduler and approvals."""
from __future__ import annotations

from typing import Any

from .actions import ActionExecutor
from .agent import Agent
from .config import Settings
from .connectors import ConnectorManager
from .db import Database
from .events import EventBus
from .llm import LLM
from .models import ModelManager
from .mcp import McpManager
from .notify import RunNotifier
from .runs import RunManager
from .scheduler import SchedulerService
from .settings_store import SettingsStore
from .skills import SkillStore
from .stores import ActionStore, AgentStore, ConversationStore, MemoryStore, ProjectStore, RunStore, ScheduleStore
from .tools import build_tools
from .uploads import UploadStore
from .variables import VariableStore


class Services:
    def __init__(self, base_settings: Settings | None = None, *, llm: Any = None, db_path: str | None = None):
        base = base_settings or Settings()
        self.db = Database(db_path or base.db_path)
        self.settings = SettingsStore(self.db, base)
        eff = self.settings.effective()
        self.bus = EventBus(self.db)
        self.llm = llm or LLM(eff)
        self.models = ModelManager(self.settings.effective)
        self.tool_names = list(build_tools())          # mutated in place when MCP tools connect
        self.mcp = McpManager(eff.data_dir / "mcp.json")
        self.connectors = ConnectorManager(self.db)
        self.agents = AgentStore(self.db, self.tool_names)
        self.schedules = ScheduleStore(self.db)
        self.runs = RunStore(self.db)
        self.memory = MemoryStore(self.db)
        self.variables = VariableStore(self.db)
        self.projects = ProjectStore(self.db)
        self.conversations = ConversationStore(self.db)
        self.uploads = UploadStore(eff.uploads_dir)
        self.action_store = ActionStore(self.db)
        self.skills = SkillStore(eff.skills_dir, legacy=eff.data_dir / "skills")
        self.scheduler = SchedulerService(self.schedules, self.agents, self.bus, self.settings.effective)
        self.executor = ActionExecutor(self.action_store, self.agents, self.schedules, self.scheduler, self.skills,
                                       self.memory, self.settings, self.bus)
        self.agent_runner = Agent(eff, self.llm, self.runs, self.bus, skills=self.skills, memory=self.memory,
                                  actions=self.executor, variables=self.variables,
                                  uploads=self.uploads, agents=self.agents)
        self.run_manager = RunManager(self.settings, self.runs, self.schedules, self.agent_runner, self.bus)
        self.scheduler.runs = self.run_manager
        self.notifier = RunNotifier(self)
        self.scheduler.uploads = self.uploads
        self.settings.on_change(self._settings_changed)
        self.assistant = None            # set in server startup (needs the assistant module)

    def _settings_changed(self, eff: Settings, keys: set[str]) -> None:
        if hasattr(self.llm, "reconfigure"):
            self.llm.reconfigure(eff)
        self.agent_runner.update_settings(eff)

    async def refresh_mcp(self) -> None:
        await self.mcp.reload()
        self.sync_mcp_tools()

    def sync_mcp_tools(self) -> None:
        base = list(build_tools())
        self.connectors.reload()
        extra = {**self.mcp.tools, **self.connectors.tools}
        self.tool_names[:] = base + list(extra)
        self.agent_runner.all_tools = {**build_tools(), **extra}

    async def startup(self, *, scheduler: bool = True) -> None:
        self.agents.ensure_default()
        self.agents.ensure_telegram(self.settings.effective().data_dir)
        await self.refresh_mcp()
        self.connectors.attach(self)            # start listeners (e.g. the Telegram bot)
        await self.run_manager.start()
        self.notifier.start()
        if scheduler:
            self.scheduler.start()

    async def shutdown(self) -> None:
        await self.notifier.stop()
        await self.connectors.stop_background()
        self.scheduler.shutdown()
        await self.mcp.shutdown()
        await self.run_manager.shutdown()
        if hasattr(self.llm, "aclose"):
            await self.llm.aclose()
        self.db.close()

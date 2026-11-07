"""MCP connectors: connect to MCP servers (stdio or streamable HTTP) and expose their tools to agents.

Config lives in ``data/mcp.json`` using the common ``mcpServers`` format::

    {"mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"], "env": {}},
        "docs": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ..."}},
        "off": {"command": "x", "disabled": true}
    }}

Each remote tool becomes a ToolSpec named ``mcp_<server>_<tool>``. Results are untrusted data and are wrapped as such.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from .browser.session import ActionError
from .tools import ToolContext, ToolOutput, ToolSpec, _truncate, _wrap

CONNECT_TIMEOUT = 30
CALL_TIMEOUT = 100


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower() or "x"


class McpManager:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.tools: dict[str, ToolSpec] = {}
        self.status: dict[str, dict] = {}      # server -> {state, tools, error}
        self._stop: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self._ready: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    def load_config(self) -> dict[str, dict]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text())
        except ValueError as e:
            self.status["_config"] = {"state": "error", "tools": 0, "error": f"invalid JSON: {e}"}
            return {}
        servers = data.get("mcpServers", data) if isinstance(data, dict) else {}
        return {k: v for k, v in servers.items() if isinstance(v, dict)}

    async def start(self) -> None:
        async with self._lock:
            await self._close()
            self.tools, self.status = {}, {}
            self._stop = asyncio.Event()
            servers = self.load_config()
            self._ready = {n: asyncio.Event() for n in servers}
            self._tasks = [asyncio.create_task(self._serve(n, c)) for n, c in servers.items()]
            # wait until every server has connected or failed
            for n in servers:
                await self._ready[n].wait()

    async def reload(self) -> None:
        await self.start()

    async def shutdown(self) -> None:
        async with self._lock:
            await self._close()
            self.tools = {}

    async def _close(self) -> None:
        if self._stop is not None:
            self._stop.set()
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._stop, self._tasks, self._ready = None, [], {}

    async def _serve(self, name: str, cfg: dict) -> None:
        """Owns one server's connection for its whole lifetime (anyio scopes must exit in the entering task)."""
        ready = self._ready[name]
        try:
            async with AsyncExitStack() as stack:
                await self._connect(name, cfg, stack)
                ready.set()
                if self.status.get(name, {}).get("state") == "connected":
                    await self._stop.wait()
        except BaseException as e:  # noqa: BLE001
            self.status.setdefault(name, {"state": "error", "tools": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"})
        finally:
            ready.set()

    async def _connect(self, name: str, cfg: dict, stack: AsyncExitStack) -> None:
        if cfg.get("disabled"):
            self.status[name] = {"state": "disabled", "tools": 0, "error": None}
            return
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):     # same task: anyio scopes must not cross tasks
                session = await self._open(cfg, stack)
                listed = await session.list_tools()
        except Exception as e:  # noqa: BLE001
            self.status[name] = {"state": "error", "tools": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            return
        n = 0
        for t in listed.tools:
            spec_name = f"mcp_{_slug(name)}_{_slug(t.name)}"
            schema = t.input_schema or {}
            ro = bool(getattr(getattr(t, "annotations", None), "read_only_hint", False))
            self.tools[spec_name] = ToolSpec(
                spec_name, f"[{name}] {(t.description or t.name).strip()}"[:400],
                dict(schema.get("properties") or {}), list(schema.get("required") or []),
                self._handler(session, t.name), side_effect=not ro)
            n += 1
        self.status[name] = {"state": "connected", "tools": n, "error": None}

    async def _open(self, cfg: dict, stack: AsyncExitStack):
        from mcp import ClientSession, StdioServerParameters
        if cfg.get("url"):
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
            http = create_mcp_http_client(headers=cfg.get("headers") or None)
            read, write = await stack.enter_async_context(streamable_http_client(cfg["url"], http_client=http))
        elif cfg.get("command"):
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=cfg["command"], args=list(cfg.get("args") or []),
                                           env=cfg.get("env") or None, cwd=cfg.get("cwd"))
            read, write = await stack.enter_async_context(stdio_client(params))
        else:
            raise ValueError("server needs `command` or `url`")
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    @staticmethod
    def _handler(session, tool_name: str):
        async def handler(ctx: ToolContext, a: dict[str, Any]) -> ToolOutput:
            try:
                res = await asyncio.wait_for(session.call_tool(tool_name, a), CALL_TIMEOUT)
            except asyncio.TimeoutError:
                raise ActionError("MCP tool timed out.") from None
            parts = []
            for c in res.content:
                text = getattr(c, "text", None)
                parts.append(text if text is not None else f"[{getattr(c, 'type', 'content')} omitted]")
            body = _truncate("\n".join(parts) or "(empty result)", ctx.settings.max_read_tokens)
            return ToolOutput(_wrap("mcp_result", body), ok=not res.is_error)
        return handler

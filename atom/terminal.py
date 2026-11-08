"""Shell command runner shared by the agent `terminal` tool and the chat assistant's `run_command` tool.

Off by default (setting `terminal_enabled`). Commands run in `terminal_dir` (default: data/workspace) with a timeout
and capped output. This is real shell access as the user running Atom: only enable it on a machine you trust, and
remember that agents read untrusted web pages.
"""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from .config import Settings

MAX_TIMEOUT = 300
MAX_OUTPUT_CHARS = 6000


class TerminalError(Exception):
    pass


def workdir(s: Settings, base: str | None = None) -> Path:
    chosen = base or s.terminal_dir
    d = Path(chosen).expanduser() if chosen else s.data_dir / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head = MAX_OUTPUT_CHARS * 2 // 3
    tail = MAX_OUTPUT_CHARS - head
    return f"{text[:head]}\n... [{len(text) - MAX_OUTPUT_CHARS} chars omitted] ...\n{text[-tail:]}"


async def run_command(s: Settings, command: str, timeout: int | None = None, cwd: str | None = None,
                      base: str | None = None) -> tuple[str, bool]:
    """Run `command` with the user's shell. Returns (text, ok). Raises TerminalError when disabled / invalid."""
    if not s.terminal_enabled:
        raise TerminalError("The terminal is disabled. The user can enable it in Settings → Terminal.")
    command = (command or "").strip()
    if not command:
        raise TerminalError("empty command")
    timeout = max(1, min(int(timeout or s.terminal_timeout_s), MAX_TIMEOUT))
    base = workdir(s, base)
    path = base
    if cwd:
        path = (base / cwd).expanduser() if not os.path.isabs(cwd) else Path(cwd)
        if not path.is_dir():
            raise TerminalError(f"cwd '{cwd}' is not a directory")
    proc = await asyncio.create_subprocess_shell(
        command, cwd=str(path), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        _kill(proc)
        await proc.wait()
        return f"Timed out after {timeout}s and was killed. Run long jobs in the background (nohup ... &).", False
    except asyncio.CancelledError:
        _kill(proc)
        raise
    text = _clip(out.decode("utf-8", "replace").strip()) or "(no output)"
    return f"{text}\n[exit code {proc.returncode}, cwd {path}]", proc.returncode == 0


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

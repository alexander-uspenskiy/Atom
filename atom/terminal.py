"""Shell command runner shared by the agent `terminal` tool and the chat assistant's `run_command` tool.

Off by default (setting `terminal_enabled`). Commands run in `terminal_dir` (default: data/workspace) with a timeout
and capped output. This is real shell access as the user running Atom: only enable it on a machine you trust, and
remember that agents read untrusted web pages.
"""
from __future__ import annotations

import asyncio
import os
import re
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


def project_prompt(s: Settings, base: str | None = None) -> str:
    """System-prompt section telling the model where its project directory is and to stay inside it."""
    d = workdir(s, base)
    return (f"Project directory: {d}\n"
            "This is the project space. Do all coding and terminal commands inside it (the terminal starts there; "
            "use paths relative to it), and save every file you create (code, documents, reports, artifacts) in it. "
            + ("Commands that reference paths outside it are blocked." if s.terminal_restrict else
               "Do not create, modify or delete files outside it unless the user explicitly asks."))


_ALLOWED_PREFIXES = ("/dev/", "/bin/", "/usr/bin/", "/usr/local/bin/", "/opt/homebrew/bin/")
_PATHISH = re.compile(r"""(?:^|[\s=:'"(<>|;&])((?:~[\w-]*|\.\.|/)[^\s'"():<>|;&]*)""")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


_HEREDOC = re.compile(r"<<-?[ \t]*(\\?)(?:'([^'\n]+)'|\"([^\"\n]+)\"|([A-Za-z_][\w]*))")
_SUBST = re.compile(r"\$\((.*?)\)|`(.*?)`", re.S)


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies so file content (HTML, code, prose) isn't mistaken for paths.

    Quoted-tag bodies (<<'EOF') are literal text, so they are removed entirely. Unquoted-tag bodies undergo shell
    expansion, so only their $(...) / `...` spans are kept for scanning.
    """
    lines = command.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in _HEREDOC.finditer(line):
            tag = m.group(2) or m.group(3) or m.group(4)
            literal = bool(m.group(1) or m.group(2) or m.group(3))
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != tag and lines[i].strip("\t") != tag:
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1                                   # closing tag line
            if not literal:
                out.extend(s.group(1) or s.group(2) for s in _SUBST.finditer("\n".join(body)))
    return "\n".join(out)


_MARKUP_TAG = re.compile(
    r"""</[A-Za-z][\w:.-]*\s*>"""                                                    # closing tag
    r"""|<[A-Za-z][\w:.-]*(?:\s+[\w:.-]+(?:=(?:\\?"[^"\\]*\\?"|'[^']*'|[^\s"'<>=\\]+))?)*\s*/?>""")  # opening tag


def _strip_quoted_markup(command: str) -> str:
    """Remove well-formed HTML/XML tags (e.g. <a href="/x">, </div>) that sit inside a quoted string.

    Quoted text is literal to the shell (double quotes are skipped when they contain $ or `), so a tag there is
    just content being written to a file, not a redirect or a path. Tags outside quotes are left alone.
    """
    out: list[str] = []
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and i + 1 < n:
            out.append(command[i:i + 2])
            i += 2
        elif c in "'\"":
            j = i + 1
            while j < n and command[j] != c:
                j += 2 if (c == '"' and command[j] == "\\") else 1
            if j >= n:                                   # unterminated quote: leave the rest untouched
                out.append(command[i:])
                break
            body = command[i + 1:j]
            if not (c == '"' and ("$" in body or "`" in body)):
                body = _MARKUP_TAG.sub("", body)
            out.append(c + body + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _check_command(command: str, base: Path, root: Path) -> None:
    """Best-effort guardrail: refuse commands that point at paths outside the project folder."""
    command = _strip_quoted_markup(_strip_heredocs(command))
    for m in _PATHISH.finditer(command):
        tok = m.group(1)
        if tok.startswith(_ALLOWED_PREFIXES) or tok == "/":
            continue
        # closing markup tag such as </div> or </a>: '<' + '/name' + '>' is not a redirect from a path
        if m.start(1) > 0 and command[m.start(1) - 1] == "<" and command[m.end(1):m.end(1) + 1] == ">":
            continue
        if tok.startswith("~"):
            p = Path(tok).expanduser()
        elif tok.startswith("/"):
            p = Path(tok)
        else:                                    # starts with ..
            p = base / tok
        if not _inside(p, root):
            raise TerminalError(
                f"Blocked by the project-folder restriction: '{tok}' is outside the project folder {root}. "
                "Work inside the project folder, or ask the user to turn off "
                "'Restrict terminal to project folder' in Settings → Terminal.")


_RO_CMDS = {"ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "wc", "pwd", "tree", "file", "stat", "du", "df",
            "echo", "which", "whoami", "date", "env", "printenv", "sort", "uniq", "cut", "diff", "basename", "dirname",
            "realpath", "find", "git"}
_RO_GIT = {"status", "log", "diff", "show", "branch", "ls-files", "rev-parse", "remote", "blame", "grep", "describe", "tag"}
_FORBIDDEN = re.compile(r"[<>;&`\n]|\$\(|\b-(?:exec|execdir|delete|ok|fprint\w*)\b")


def is_read_only(command: str) -> bool:
    """True only for simple inspection commands (ls, cat, grep, git status ...). Used by Plan mode."""
    command = (command or "").strip()
    if not command or _FORBIDDEN.search(command):
        return False
    for seg in command.split("|"):
        words = seg.split()
        if not words or words[0] not in _RO_CMDS:
            return False
        if words[0] == "git":
            sub = next((w for w in words[1:] if not w.startswith("-")), "")
            if sub not in _RO_GIT or (sub in ("branch", "tag", "remote") and len([w for w in words[2:] if not w.startswith("-")]) > 0
                                       and not any(w in ("-l", "--list", "-v", "-a", "-r") for w in words)):
                return False
    return True


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
    if s.terminal_restrict:
        if not _inside(path, base):
            raise TerminalError(f"Blocked by the project-folder restriction: cwd '{cwd}' is outside {base}. "
                                "Turn off 'Restrict terminal to project folder' in Settings → Terminal to allow it.")
        _check_command(command, path, base)
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

"""File tools shared by the agent and the chat assistant: write, read, edit, list, mkdir, move, delete.

These exist so models never have to push file content through the shell (where quoting, heredocs and the terminal
guard get in the way). Content travels as a JSON argument and is written verbatim.

Gated by the same `terminal_enabled` setting as the terminal. Paths are relative to the project folder; while
`terminal_restrict` is on (default) every path must resolve inside it, symlinks included.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import Settings
from .terminal import workdir

MAX_WRITE_CHARS = 400_000
MAX_READ_CHARS = 12_000
MAX_LIST = 300
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".DS_Store"}


class FileError(Exception):
    pass


def _check_enabled(s: Settings) -> None:
    if not s.terminal_enabled:
        raise FileError("File tools are disabled. The user can enable them with 'Enable terminal' in Settings → Terminal.")


def resolve(s: Settings, path: str, base: str | None = None) -> tuple[Path, Path]:
    """Return (absolute path, project root). Raises FileError if disabled or outside the project folder."""
    _check_enabled(s)
    root = workdir(s, base).resolve()
    raw = (path or "").strip()
    if not raw:
        raise FileError("path is required")
    p = Path(raw).expanduser()
    p = (p if p.is_absolute() else root / p)
    p = Path(os.path.normpath(p))
    if s.terminal_restrict:
        try:
            p.resolve().relative_to(root)           # resolve() follows symlinks, so links can't escape
        except ValueError:
            raise FileError(f"Blocked by the project-folder restriction: '{path}' is outside the project folder {root}. "
                            "Use a path inside it, or ask the user to turn off 'Restrict terminal to project folder' "
                            "in Settings → Terminal.") from None
    return p, root


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.resolve().relative_to(root))
    except ValueError:
        return str(p)


def write_file(s: Settings, path: str, content: str, append: bool = False, base: str | None = None) -> str:
    p, root = resolve(s, path, base)
    content = "" if content is None else str(content)
    if len(content) > MAX_WRITE_CHARS:
        raise FileError(f"content too large ({len(content)} chars, max {MAX_WRITE_CHARS}); split it over several calls "
                        "with append=true")
    if p.is_dir():
        raise FileError(f"'{path}' is a directory")
    existed = p.exists()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as e:
        raise FileError(f"could not write '{path}': {e.strerror or e}") from e
    verb = "Appended to" if append else ("Overwrote" if existed else "Created")
    return f"{verb} {_rel(p, root)} ({len(content.encode('utf-8'))} bytes, {content.count(chr(10)) + (1 if content and not content.endswith(chr(10)) else 0)} lines)."


def read_file(s: Settings, path: str, offset: int = 0, length: int = 0, base: str | None = None) -> str:
    p, root = resolve(s, path, base)
    if not p.is_file():
        raise FileError(f"'{path}' is not a file" if p.exists() else f"'{path}' does not exist")
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise FileError(f"could not read '{path}': {e.strerror or e}") from e
    if b"\0" in raw[:4096]:
        raise FileError(f"'{path}' looks like a binary file ({len(raw)} bytes)")
    text = raw.decode("utf-8", "replace")
    offset = max(0, int(offset or 0))
    length = max(1, min(int(length or MAX_READ_CHARS), MAX_READ_CHARS))
    chunk = text[offset:offset + length]
    end = offset + len(chunk)
    tail = f"\n[showing chars {offset}-{end} of {len(text)}; call again with offset={end} for more]" if end < len(text) else ""
    return (chunk or "(empty)") + tail


def edit_file(s: Settings, path: str, old: str, new: str, replace_all: bool = False, base: str | None = None) -> str:
    p, root = resolve(s, path, base)
    if not p.is_file():
        raise FileError(f"'{path}' does not exist; use write_file to create it")
    old, new = str(old if old is not None else ""), str(new if new is not None else "")
    if not old:
        raise FileError("`old` must be the exact existing text to replace (not empty)")
    text = p.read_text(encoding="utf-8", errors="replace")
    n = text.count(old)
    if n == 0:
        raise FileError("`old` text not found. Read the file again and copy the text exactly, including whitespace.")
    if n > 1 and not replace_all:
        raise FileError(f"`old` matches {n} places. Add more surrounding text to make it unique, or set replace_all=true.")
    p.write_text(text.replace(old, new) if replace_all else text.replace(old, new, 1), encoding="utf-8")
    return f"Edited {_rel(p, root)}: replaced {n if replace_all else 1} occurrence(s)."


def list_files(s: Settings, path: str = ".", depth: int = 2, base: str | None = None) -> str:
    p, root = resolve(s, path or ".", base)
    if not p.is_dir():
        raise FileError(f"'{path}' is not a directory" if p.exists() else f"'{path}' does not exist")
    depth = max(1, min(int(depth or 2), 6))
    lines: list[str] = []

    def walk(d: Path, level: int) -> None:
        try:
            entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for e in entries:
            if len(lines) >= MAX_LIST:
                return
            if e.name in _SKIP_DIRS:
                continue
            rel = _rel(e, root) if e.resolve().is_relative_to(root) else str(e)
            if e.is_dir():
                lines.append(rel + "/")
                if level < depth and not e.is_symlink():
                    walk(e, level + 1)
            else:
                try:
                    lines.append(f"{rel}  ({e.stat().st_size} B)")
                except OSError:
                    lines.append(rel)

    walk(p, 1)
    if not lines:
        return "(empty)"
    more = f"\n[list truncated at {MAX_LIST} entries]" if len(lines) >= MAX_LIST else ""
    return "\n".join(lines) + more


def make_dir(s: Settings, path: str, base: str | None = None) -> str:
    p, root = resolve(s, path, base)
    if p.exists() and not p.is_dir():
        raise FileError(f"'{path}' exists and is not a directory")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FileError(f"could not create '{path}': {e.strerror or e}") from e
    return f"Directory {_rel(p, root)} is ready."


def move_file(s: Settings, src: str, dest: str, overwrite: bool = False, base: str | None = None) -> str:
    a, root = resolve(s, src, base)
    b, _ = resolve(s, dest, base)
    if not a.exists():
        raise FileError(f"'{src}' does not exist")
    if b.is_dir():
        b = b / a.name
    if b.exists() and not overwrite:
        raise FileError(f"'{dest}' already exists; set overwrite=true to replace it")
    if a.resolve() == root:
        raise FileError("cannot move the project folder itself")
    try:
        b.parent.mkdir(parents=True, exist_ok=True)
        if b.exists() and b.is_file():
            b.unlink()
        shutil.move(str(a), str(b))
    except OSError as e:
        raise FileError(f"could not move '{src}': {e.strerror or e}") from e
    return f"Moved {_rel(a, root) if a.exists() else src} -> {_rel(b, root)}."


def delete_file(s: Settings, path: str, recursive: bool = False, base: str | None = None) -> str:
    p, root = resolve(s, path, base)
    if not (p.exists() or p.is_symlink()):
        raise FileError(f"'{path}' does not exist")
    if p.resolve() == root:
        raise FileError("refusing to delete the project folder itself")
    try:
        if p.is_symlink() or p.is_file():
            p.unlink()
            return f"Deleted file {path}."
        if recursive:
            n = sum(len(f) for _, _, f in os.walk(p))
            shutil.rmtree(p)
            return f"Deleted folder {path} and its {n} file(s)."
        p.rmdir()
        return f"Deleted empty folder {path}."
    except OSError as e:
        if e.errno in (39, 66):                   # ENOTEMPTY (linux / macOS)
            raise FileError(f"folder '{path}' is not empty; set recursive=true to delete it with its contents") from e
        raise FileError(f"could not delete '{path}': {e.strerror or e}") from e


# name -> (callable taking (settings, args, base), writes?)
def dispatch(s: Settings, name: str, a: dict, base: str | None = None) -> str:
    b = lambda v: v if isinstance(v, bool) else str(v).lower() == "true"          # noqa: E731
    if name == "write_file":
        return write_file(s, str(a["path"]), a.get("content", ""), b(a.get("append", False)), base)
    if name == "read_file":
        return read_file(s, str(a["path"]), a.get("offset") or 0, a.get("length") or 0, base)
    if name == "edit_file":
        return edit_file(s, str(a["path"]), a.get("old", ""), a.get("new", ""), b(a.get("replace_all", False)), base)
    if name == "list_files":
        return list_files(s, str(a.get("path") or "."), a.get("depth") or 2, base)
    if name == "make_dir":
        return make_dir(s, str(a["path"]), base)
    if name == "move_file":
        return move_file(s, str(a["src"]), str(a["dest"]), b(a.get("overwrite", False)), base)
    if name == "delete_file":
        return delete_file(s, str(a["path"]), b(a.get("recursive", False)), base)
    raise FileError(f"unknown file tool {name}")


FILE_TOOLS = ("write_file", "read_file", "edit_file", "list_files", "make_dir", "move_file", "delete_file")
WRITE_TOOLS = {"write_file", "edit_file", "make_dir", "move_file", "delete_file"}       # change the disk

S = {"type": "string"}
B = {"type": "boolean"}
TOOL_DEFS: dict[str, tuple[str, dict, list[str]]] = {
    "write_file": ("Create or overwrite a text file with the given content (written verbatim; parent folders are created). "
                   "Use this for every file you create instead of shell heredocs. For big files write the first part, "
                   "then add the rest with append=true. Path is relative to the project folder.",
                   {"path": S, "content": S, "append": B}, ["path", "content"]),
    "read_file": ("Read a text file from the project folder (up to 12000 chars per call; use offset to continue).",
                  {"path": S, "offset": {"type": "integer"}, "length": {"type": "integer"}}, ["path"]),
    "edit_file": ("Change part of an existing file: replace the exact text `old` with `new`. `old` must match once "
                  "(or set replace_all=true). Prefer this over rewriting the whole file for small changes.",
                  {"path": S, "old": S, "new": S, "replace_all": B}, ["path", "old", "new"]),
    "list_files": ("List files and folders (with sizes) under a project folder path, default the project root.",
                   {"path": S, "depth": {"type": "integer"}}, []),
    "make_dir": ("Create a folder (and parents) in the project folder.", {"path": S}, ["path"]),
    "move_file": ("Move or rename a file or folder inside the project folder.",
                  {"src": S, "dest": S, "overwrite": B}, ["src", "dest"]),
    "delete_file": ("Delete a file or an empty folder. Folders with contents need recursive=true. Only delete what the "
                    "user asked for or what you created yourself.",
                    {"path": S, "recursive": B}, ["path"]),
}

PROMPT = ("File tools: write_file, edit_file, read_file, list_files, make_dir, move_file and delete_file work directly on "
          "files in the project folder. Always create and change files with them, never with shell heredocs or echo "
          "redirects; content is passed as-is, so HTML, code and quotes need no escaping. Use the terminal only to run things.")

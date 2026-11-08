"""Skills: reusable procedures stored as <root>/<name>/SKILL.md (YAML frontmatter + markdown body).

Two levels:
- user skills   live in ~/.atom/skills (override with ATOM_SKILLS_DIR) and are available everywhere;
- project skills live inside a project folder, in `<folder>/.atom/skills` or `<folder>/.agents/skills`, and are
  available only when working in that folder (a chat project, or an agent whose working folder it is).
A project skill with the same name as a user skill wins.

Progressive disclosure: a system prompt only carries a one-line catalog entry per skill; the full body is
loaded on demand with the `use_skill` tool, so skills cost almost nothing until they are used.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .stores import Conflict, Invalid, NotFound

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PROJECT_SUBDIRS = (".atom/skills", ".agents/skills")     # first one is where new project skills are written
KNOWN_KEYS = ("name", "description", "when_to_use", "enabled", "created_by")


def _split(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), parts[2]
    return {}, text


class SkillStore:
    def __init__(self, root: Path, legacy: Path | None = None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        # Skills used to live in data/skills: copy them to the user folder once (never overwrite, never delete).
        if legacy and legacy.is_dir() and legacy.resolve() != root.resolve():
            for p in legacy.glob("*/SKILL.md"):
                dest = root / p.parent.name / "SKILL.md"
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)

    # ------------------------------------------------------------------ locations
    @staticmethod
    def _slug(name: str) -> str:
        if not SLUG.match(name or ""):
            raise Invalid("skill name must be a lowercase slug: a-z, 0-9 and dashes (max 63 chars)")
        return name

    @staticmethod
    def _project_roots(folder: str | Path | None) -> list[Path]:
        if not folder:
            return []
        base = Path(folder).expanduser()
        return [base / sub for sub in PROJECT_SUBDIRS]

    def _roots(self, folder: str | Path | None) -> list[tuple[str, Path]]:
        """(scope, root) in priority order: project folders first, then the user folder."""
        return [("project", r) for r in self._project_roots(folder)] + [("user", self.root)]

    def _find(self, name: str, folder: str | Path | None) -> tuple[str, Path] | None:
        self._slug(name)
        for scope, root in self._roots(folder):
            if (root / name / "SKILL.md").is_file():
                return scope, root
        return None

    @staticmethod
    def _parse(path: Path, scope: str) -> dict[str, Any]:
        meta, body = _split(path.read_text(encoding="utf-8"))
        return {"name": path.parent.name, "description": str(meta.get("description") or ""),
                "when_to_use": str(meta.get("when_to_use") or ""), "body": body.strip(),
                "enabled": bool(meta.get("enabled", True)), "created_by": str(meta.get("created_by") or "user"),
                "updated_at": path.stat().st_mtime, "scope": scope, "path": str(path)}

    # ------------------------------------------------------------------ read
    def list(self, folder: str | Path | None = None) -> list[dict]:
        seen: dict[str, dict] = {}
        for scope, root in self._roots(folder):
            for p in sorted(root.glob("*/SKILL.md")):
                if p.parent.name in seen or not SLUG.match(p.parent.name):
                    continue
                try:
                    seen[p.parent.name] = self._parse(p, scope)
                except OSError:
                    continue
        return sorted(seen.values(), key=lambda s: s["name"])

    def get(self, name: str, folder: str | Path | None = None) -> dict:
        hit = self._find(name, folder)
        if not hit:
            raise NotFound(f"skill {name} not found")
        scope, root = hit
        return self._parse(root / name / "SKILL.md", scope)

    def project_names(self, folder: str | Path | None) -> list[str]:
        """Enabled project-level skill names for a folder (empty when there is no folder)."""
        return [s["name"] for s in self.list(folder) if s["scope"] == "project" and s["enabled"]]

    def catalog(self, names: list[str], folder: str | Path | None = None) -> list[dict]:
        """Enabled skills among `names`, for the system prompt."""
        out = []
        for n in names:
            try:
                s = self.get(n, folder)
            except (NotFound, Invalid):
                continue
            if s["enabled"]:
                out.append(s)
        return out

    # ------------------------------------------------------------------ write
    def _write(self, root: Path, name: str, d: dict) -> None:
        p = root / name / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        extra: dict[str, Any] = {}
        if p.exists():          # keep frontmatter keys we do not manage (e.g. from skills authored elsewhere)
            extra = {k: v for k, v in _split(p.read_text(encoding="utf-8"))[0].items() if k not in KNOWN_KEYS}
        meta = {"name": name, "description": d.get("description", ""), "when_to_use": d.get("when_to_use", ""),
                "enabled": bool(d.get("enabled", True)), "created_by": d.get("created_by", "user"), **extra}
        p.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"
                     + (d.get("body") or "").strip() + "\n", encoding="utf-8")

    def create(self, d: dict, folder: str | Path | None = None) -> dict:
        """`d["scope"]` is "user" (default) or "project" (needs `folder`: the project's working folder)."""
        name = self._slug((d.get("name") or "").strip())
        if not (d.get("body") or "").strip():
            raise Invalid("body is required")
        if not (d.get("description") or "").strip():
            raise Invalid("description is required")
        scope = d.get("scope") or "user"
        if scope == "project":
            if not folder:
                raise Invalid("a project skill needs a project with a working folder")
            root = self._project_roots(folder)[0]
        elif scope == "user":
            root = self.root
        else:
            raise Invalid("scope must be 'user' or 'project'")
        if (root / name / "SKILL.md").exists():
            raise Conflict(f"skill '{name}' already exists in the {scope} skills")
        self._write(root, name, d)
        return self._parse(root / name / "SKILL.md", scope)

    def update(self, name: str, d: dict, folder: str | Path | None = None) -> dict:
        cur = self.get(name, folder)
        merged = {**cur, **{k: v for k, v in d.items() if k in ("description", "when_to_use", "body", "enabled")}}
        if not (merged["body"] or "").strip():
            raise Invalid("body is required")
        root = Path(cur["path"]).parent.parent
        self._write(root, name, merged)
        return self._parse(root / name / "SKILL.md", cur["scope"])

    def delete(self, name: str, folder: str | Path | None = None) -> None:
        cur = self.get(name, folder)
        shutil.rmtree(Path(cur["path"]).parent, ignore_errors=True)

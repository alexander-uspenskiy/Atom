"""Skills: reusable procedures stored as data/skills/<name>/SKILL.md (YAML frontmatter + markdown body).

Progressive disclosure: an agent's system prompt only carries a one-line catalog entry per skill; the full body is
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


class SkillStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _file(self, name: str) -> Path:
        if not SLUG.match(name):
            raise Invalid("skill name must be a lowercase slug: a-z, 0-9 and dashes (max 63 chars)")
        return self.root / name / "SKILL.md"

    @staticmethod
    def _parse(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    meta = {}
                body = parts[2]
        return {"name": str(meta.get("name") or path.parent.name), "description": str(meta.get("description") or ""),
                "when_to_use": str(meta.get("when_to_use") or ""), "body": body.strip(),
                "enabled": bool(meta.get("enabled", True)), "created_by": str(meta.get("created_by") or "user"),
                "updated_at": path.stat().st_mtime}

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.root.glob("*/SKILL.md")):
            try:
                out.append(self._parse(p))
            except OSError:
                continue
        return out

    def get(self, name: str) -> dict:
        p = self._file(name)
        if not p.exists():
            raise NotFound(f"skill {name} not found")
        return self._parse(p)

    def _write(self, name: str, d: dict) -> dict:
        p = self._file(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        meta = {"name": name, "description": d.get("description", ""), "when_to_use": d.get("when_to_use", ""),
                "enabled": bool(d.get("enabled", True)), "created_by": d.get("created_by", "user")}
        p.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"
                     + (d.get("body") or "").strip() + "\n", encoding="utf-8")
        return self.get(name)

    def create(self, d: dict) -> dict:
        name = (d.get("name") or "").strip()
        if not (d.get("body") or "").strip():
            raise Invalid("body is required")
        if not (d.get("description") or "").strip():
            raise Invalid("description is required")
        if self._file(name).exists():
            raise Conflict(f"skill '{name}' already exists")
        return self._write(name, d)

    def update(self, name: str, d: dict) -> dict:
        cur = self.get(name)
        merged = {**cur, **{k: v for k, v in d.items() if k in ("description", "when_to_use", "body", "enabled")}}
        if not (merged["body"] or "").strip():
            raise Invalid("body is required")
        return self._write(name, merged)

    def delete(self, name: str) -> None:
        self.get(name)
        shutil.rmtree(self._file(name).parent, ignore_errors=True)

    def catalog(self, names: list[str]) -> list[dict]:
        """Enabled skills among `names`, for the system prompt."""
        out = []
        for n in names:
            try:
                s = self.get(n)
            except (NotFound, Invalid):
                continue
            if s["enabled"]:
                out.append(s)
        return out

"""Environment & secret variables that agents can use via {{NAME}} placeholders in tool arguments.

Non-secret values are shown to the model (in the system prompt) and substituted into any tool call.
Secret values are never shown to the model: they are substituted into the arguments of a few tools only
(typing, selecting, opening URLs and MCP tools), optionally only while the page is on an allowed domain,
and are scrubbed from tool output before it is stored or sent back to the model.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .db import Database, jdump, jload, now
from .stores import Invalid, NotFound

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*\}\}")
SECRET_TOOLS = {"type", "select_option", "open_url"}      # plus every mcp_* tool
NEVER_SUBSTITUTE = {"done", "note", "remember"}
MIN_REDACT_LEN = 4


def _host(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _domain_ok(host: str, domains: list[str]) -> bool:
    return not domains or any(host == d or host.endswith("." + d) for d in domains)


class VariableStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _out(r) -> dict:
        secret = bool(r["secret"])
        return {"name": r["name"], "secret": secret, "value": None if secret else r["value"],
                "has_value": bool(r["value"]), "description": r["description"] or "",
                "domains": jload(r["domains"], []), "updated_at": r["updated_at"]}

    def list(self) -> list[dict]:
        return [self._out(r) for r in self.db.all("SELECT * FROM variables ORDER BY secret, name")]

    def put(self, name: str, *, value: str | None, secret: bool, description: str = "",
            domains: list[str] | None = None) -> dict:
        if not NAME_RE.match(name):
            raise Invalid("Name must start with a letter or _ and use only letters, digits and _ (max 64).")
        doms = sorted({d.strip().lower().lstrip(".") for d in (domains or []) if d.strip()})
        old = self.db.one("SELECT * FROM variables WHERE name=?", (name,))
        if value is None:
            if old is None:
                raise Invalid("A value is required for a new variable.")
            value = old["value"]                      # keep the stored value (secrets are never sent back)
        if "\n" in value and not secret and len(value) > 2000:
            raise Invalid("Value is too long.")
        t = now()
        self.db.execute(
            "INSERT INTO variables (name, value, secret, description, domains, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value, secret=excluded.secret, "
            "description=excluded.description, domains=excluded.domains, updated_at=excluded.updated_at",
            (name, value, int(secret), description.strip()[:300], jdump(doms), t, t))
        return self._out(self.db.one("SELECT * FROM variables WHERE name=?", (name,)))

    def delete(self, name: str) -> None:
        if self.db.execute("DELETE FROM variables WHERE name=?", (name,)).rowcount == 0:
            raise NotFound(f"variable '{name}' not found")

    # ---------------------------------------------------------------- agent side
    def snapshot(self) -> "VariableSet":
        rows = self.db.all("SELECT * FROM variables")
        return VariableSet({r["name"]: {"value": r["value"], "secret": bool(r["secret"]),
                                        "description": r["description"] or "", "domains": jload(r["domains"], [])}
                            for r in rows if r["value"]})


class VariableSet:
    """Immutable view of the variables at the start of a run."""

    def __init__(self, items: dict[str, dict]):
        self.items = items

    def __bool__(self) -> bool:
        return bool(self.items)

    def prompt_section(self) -> str:
        if not self.items:
            return ""
        lines = ["Variables you can use: write {{NAME}} inside a tool argument and the real value is filled in "
                 "automatically when the tool runs. Secret values are hidden from you; never try to read, "
                 "print or guess them, and never put them in `note`, `remember` or `done`."]
        for n, v in sorted(self.items.items()):
            desc = f" - {v['description']}" if v["description"] else ""
            if v["secret"]:
                where = f" (only on {', '.join(v['domains'])})" if v["domains"] else ""
                lines.append(f"- {{{{{n}}}}} [secret{where}]{desc}")
            else:
                lines.append(f"- {{{{{n}}}}} = {v['value']}{desc}")
        return "\n".join(lines)

    def apply(self, tool: str, args: dict[str, Any], page_url: str | None) -> tuple[dict[str, Any], str | None]:
        """Return (args with placeholders filled, error). Unknown placeholders are left as written."""
        if not self.items or tool in NEVER_SUBSTITUTE:
            return args, None
        secrets_ok = tool in SECRET_TOOLS or tool.startswith("mcp_")
        host = _host(page_url)
        err: list[str] = []

        def sub_text(s: str) -> str:
            def one(m: re.Match) -> str:
                v = self.items.get(m.group(1))
                if v is None:
                    return m.group(0)
                if v["secret"]:
                    if not secrets_ok:
                        err.append(f"{m.group(1)} is a secret and cannot be used with {tool}.")
                        return m.group(0)
                    # open_url fills the secret into a URL the model chooses, so its target host is checked too
                    check = _host(s) if tool == "open_url" else host
                    if v["domains"] and not _domain_ok(check, v["domains"]):
                        err.append(f"{m.group(1)} may only be used on {', '.join(v['domains'])} "
                                   f"(current: {check or 'no page'}).")
                        return m.group(0)
                return v["value"]
            return PLACEHOLDER.sub(one, s)

        def walk(x: Any) -> Any:
            if isinstance(x, str):
                return sub_text(x)
            if isinstance(x, list):
                return [walk(i) for i in x]
            if isinstance(x, dict):
                return {k: walk(v) for k, v in x.items()}
            return x

        new = walk(args)
        return (args, err[0]) if err else (new, None)

    def redact(self, text: str) -> str:
        for n, v in self.items.items():
            if v["secret"] and len(v["value"]) >= MIN_REDACT_LEN:
                text = text.replace(v["value"], f"{{{{{n}}}}}")
        return text

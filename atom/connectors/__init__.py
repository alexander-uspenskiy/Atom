"""Connectors: configurable integrations (Gmail, ...) that give agents extra tools.

To add a connector, subclass `Connector` in a new module, declare its `fields` (the UI form is generated from them)
and implement `build_tools`, then `register(MyConnector())`. Nothing else (API, UI, agent tool lists) needs changing.
MCP servers are managed separately (atom/mcp.py); connectors are for first-party integrations.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from ..db import Database, jdump, jload, now
from ..stores import Invalid, NotFound
from ..tools import ToolSpec
from . import secrets
from .oauth import REFRESH_KEY, AuthError, AuthRequired, OAuthFlows, TokenSource

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,30}$")


class Connector:
    type: str = ""
    label: str = ""
    description: str = ""
    # Each field: {key, label, type: text|password|boolean|number, required?, default?, help?, placeholder?}
    # `password` fields are secrets: stored, never returned by the API, kept when left blank on edit.
    fields: list[dict[str, Any]] = []
    # Optional browser sign-in: {auth_url, token_url, scopes, client_id_key, client_secret_key}. When set, a refresh
    # token is kept in the keychain and build_tools receives cfg["token_provider"] (callable -> access token).
    oauth: dict[str, Any] | None = None

    def validate(self, cfg: dict[str, Any]) -> None:
        """Raise Invalid for a bad config (called on save)."""

    def build_tools(self, name: str, cfg: dict[str, Any]) -> dict[str, ToolSpec]:
        raise NotImplementedError

    async def test(self, cfg: dict[str, Any]) -> str:
        """Check the credentials/connection; return a short success message or raise."""
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"type": self.type, "label": self.label, "description": self.description, "fields": self.fields,
                "oauth": self.oauth is not None}


REGISTRY: dict[str, Connector] = {}


def register(c: Connector) -> None:
    REGISTRY[c.type] = c


def _secret_keys(c: Connector) -> set[str]:
    return {f["key"] for f in c.fields if f["type"] == "password"}


class ConnectorManager:
    def __init__(self, db: Database):
        self.db = db
        self.tools: dict[str, ToolSpec] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self.flows = OAuthFlows()
        self._resolved: dict[str, dict[str, Any]] = {}      # name -> config incl. secrets (memory only)
        self._migrate_plaintext_secrets()
        self.reload()

    def _migrate_plaintext_secrets(self) -> None:
        for r in self._rows():
            c = REGISTRY.get(r["type"])
            cfg = jload(r["config"], {})
            moved = [k for k in (_secret_keys(c) if c else ()) if cfg.get(k)]
            if moved:
                for k in moved:
                    secrets.put(r["name"], k, cfg.pop(k))
                self.db.execute("UPDATE connectors SET config=? WHERE name=?", (jdump(cfg), r["name"]))

    # ------------------------------------------------------------------ storage
    def _rows(self) -> list:
        return self.db.all("SELECT * FROM connectors ORDER BY name")

    def _out(self, r) -> dict:
        c = REGISTRY.get(r["type"])
        cfg = jload(r["config"], {})
        res = self._resolved.get(r["name"], {})
        blank = {"state": "disabled" if not r["enabled"] else "pending", "error": None, "tool_names": []}
        return {"name": r["name"], "type": r["type"], "enabled": bool(r["enabled"]), "config": cfg,
                "has_secret": {k: bool(res.get(k)) for k in (_secret_keys(c) if c else ())},
                "signed_in": bool(res.get(REFRESH_KEY)),
                **self.status.get(r["name"], blank)}

    def list(self) -> list[dict]:
        return [self._out(r) for r in self._rows()]

    def payload(self) -> dict:
        return {"types": [c.describe() for c in REGISTRY.values()], "items": self.list()}

    def put(self, name: str, ctype: str, enabled: bool, config: dict[str, Any]) -> dict:
        if not NAME_RE.match(name):
            raise Invalid("Name must be 1-30 letters, digits, '-' or '_'.")
        c = REGISTRY.get(ctype)
        if c is None:
            raise Invalid(f"unknown connector type '{ctype}'. Available: {', '.join(REGISTRY)}")
        old = self.db.one("SELECT * FROM connectors WHERE name=?", (name,))
        if old is not None and old["type"] != ctype:
            raise Invalid("A connector's type cannot be changed; delete it and add a new one.")
        prev = jload(old["config"], {}) if old else {}
        sec_keys = _secret_keys(c)
        cfg: dict[str, Any] = {}
        new_secrets: dict[str, str] = {}
        for f in c.fields:
            k = f["key"]
            v = config.get(k)
            if f["type"] == "password":
                if v not in (None, ""):
                    new_secrets[k] = str(v).strip()          # blank = keep what is stored
                continue
            if f["type"] == "boolean":
                v = bool(v) if v is not None else bool(f.get("default", False))
            elif isinstance(v, str):
                v = v.strip()
            if f.get("required") and v in (None, ""):
                raise Invalid(f"{f['label']} is required.")
            if v not in (None, ""):
                cfg[k] = v
        merged = {**cfg, **{k: secrets.get(name, k) for k in sec_keys}, **new_secrets}
        c.validate({k: v for k, v in merged.items() if v})
        for k, v in new_secrets.items():
            secrets.put(name, k, v)
        if c.oauth and (cfg.get(c.oauth["client_id_key"]) != prev.get(c.oauth["client_id_key"]) or
                        c.oauth["client_secret_key"] in new_secrets):
            secrets.delete(name, REFRESH_KEY)                  # tokens belong to the old client; sign in again
        t = now()
        self.db.execute(
            "INSERT INTO connectors (name, type, config, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET config=excluded.config, enabled=excluded.enabled, updated_at=excluded.updated_at",
            (name, ctype, jdump(cfg), int(enabled), t, t))
        self.reload()
        return self._out(self.db.one("SELECT * FROM connectors WHERE name=?", (name,)))

    def delete(self, name: str) -> None:
        r = self.db.one("SELECT * FROM connectors WHERE name=?", (name,))
        if r is None:
            raise NotFound(f"connector '{name}' not found")
        c = REGISTRY.get(r["type"])
        for k in (_secret_keys(c) if c else set()) | {REFRESH_KEY}:
            secrets.delete(name, k)
        self.db.execute("DELETE FROM connectors WHERE name=?", (name,))
        self.reload()

    # ------------------------------------------------------------------ tools
    def reload(self) -> None:
        tools: dict[str, ToolSpec] = {}
        status: dict[str, dict[str, Any]] = {}
        resolved: dict[str, dict[str, Any]] = {}
        for r in self._rows():
            c = REGISTRY.get(r["type"])
            name = r["name"]
            cfg = jload(r["config"], {})
            for k in (_secret_keys(c) if c else set()) | {REFRESH_KEY}:
                v = secrets.get(name, k)
                if v:
                    cfg[k] = v
            if c is not None and c.oauth and cfg.get(REFRESH_KEY) and cfg.get(c.oauth["client_id_key"]):
                cfg["token_provider"] = TokenSource(c.oauth, cfg[c.oauth["client_id_key"]],
                                                    cfg.get(c.oauth["client_secret_key"], ""), cfg[REFRESH_KEY])
            resolved[name] = cfg
            if not r["enabled"]:
                status[name] = {"state": "disabled", "error": None, "tool_names": []}
            elif c is None:
                status[name] = {"state": "error", "error": f"unknown connector type '{r['type']}'", "tool_names": []}
            else:
                try:
                    built = c.build_tools(name, cfg)
                except AuthRequired as e:
                    status[name] = {"state": "needs_auth", "error": str(e), "tool_names": []}
                    continue
                except Exception as e:  # noqa: BLE001
                    status[name] = {"state": "error", "error": str(e), "tool_names": []}
                    continue
                tools.update(built)
                status[name] = {"state": "ready", "error": None, "tool_names": list(built)}
        self.tools, self.status, self._resolved = tools, status, resolved

    async def test(self, name: str) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM connectors WHERE name=?", (name,))
        if r is None:
            raise NotFound(f"connector '{name}' not found")
        c = REGISTRY.get(r["type"])
        if c is None:
            return {"ok": False, "message": f"unknown connector type '{r['type']}'"}
        try:
            msg = await asyncio.wait_for(c.test(self._resolved.get(name, {})), 30)
            return {"ok": True, "message": msg}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": f"{type(e).__name__}: {e}"[:300]}

    # ------------------------------------------------------------------ browser sign-in
    def _oauth_spec(self, name: str) -> tuple[Connector, dict, dict]:
        r = self.db.one("SELECT * FROM connectors WHERE name=?", (name,))
        if r is None:
            raise NotFound(f"connector '{name}' not found")
        c = REGISTRY.get(r["type"])
        if c is None or not c.oauth:
            raise Invalid("This connector does not use browser sign-in.")
        return c, c.oauth, self._resolved.get(name, {})

    def oauth_begin(self, name: str, redirect_uri: str) -> str:
        c, spec, cfg = self._oauth_spec(name)
        cid, csec = cfg.get(spec["client_id_key"]), cfg.get(spec["client_secret_key"])
        if not cid or not csec:
            raise Invalid("Save the Google OAuth client ID and secret first.")
        return self.flows.begin(name, spec, cid, csec, redirect_uri, cfg.get("email"))

    async def oauth_complete(self, state: str, code: str) -> str:
        try:
            name, refresh = await self.flows.finish(state, code)
        except AuthError as e:
            raise Invalid(str(e)) from e
        secrets.put(name, REFRESH_KEY, refresh)
        self.reload()
        return name

    def oauth_signout(self, name: str) -> None:
        self._oauth_spec(name)
        secrets.delete(name, REFRESH_KEY)
        self.reload()


from . import gmail  # noqa: E402,F401  (registers itself)

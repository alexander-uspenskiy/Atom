"""CRUD stores over the SQLite database: agents, schedules, runs, memories, conversations, approvals."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .db import Database, jdump, jload, new_id, now


class NotFound(KeyError):
    pass


class Invalid(ValueError):
    pass


class Conflict(ValueError):
    pass


# =============================================================================== agents
THINKING = ("inherit", "off", "auto", "on")
EFFORT = ("inherit", "low", "medium", "xhigh")
MEM_SCOPE = ("none", "global", "agent")


class AgentStore:
    def __init__(self, db: Database, tool_names: list[str]):
        self.db, self.tool_names = db, tool_names

    @staticmethod
    def _out(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "name": r["name"], "description": r["description"] or "",
                "instructions": r["instructions"] or "", "start_url": r["start_url"],
                "allowed_domains": jload(r["allowed_domains"], []), "allow_private": bool(r["allow_private"]),
                "tools": jload(r["tools"], None), "skills": jload(r["skills"], []), "memory_scope": r["memory_scope"],
                "thinking": r["thinking"], "effort": r["effort"], "max_steps": r["max_steps"],
                "temperature": r["temperature"], "profile": r["profile"], "workdir": r["workdir"], "is_default": bool(r["is_default"]),
                "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def _clean(self, d: dict, partial: bool = False) -> dict:
        out: dict[str, Any] = {}
        if "name" in d or not partial:
            name = (d.get("name") or "").strip()
            if not name:
                raise Invalid("name is required")
            out["name"] = name
        for k in ("description", "instructions", "start_url", "profile"):
            if k in d:
                out[k] = (d[k] or None) if k in ("start_url", "profile") else (d[k] or "")
        if "workdir" in d:
            wd = str(d["workdir"] or "").strip()
            if wd:
                wd = str(Path(wd).expanduser())
                if not Path(wd).is_dir():
                    raise Invalid(f"working folder '{wd}' does not exist")
            out["workdir"] = wd or None
        if "allowed_domains" in d:
            doms = [str(x).strip().lower() for x in (d["allowed_domains"] or []) if str(x).strip()]
            out["allowed_domains"] = jdump(doms)
        if "allow_private" in d:
            out["allow_private"] = int(bool(d["allow_private"]))
        if "tools" in d:
            tools = d["tools"]
            if tools is not None:
                unknown = [t for t in tools if t not in self.tool_names]
                if unknown:
                    raise Invalid(f"unknown tool(s): {', '.join(unknown)}")
                tools = sorted(set(tools) | {"done"})      # an agent must always be able to finish
            out["tools"] = None if tools is None else jdump(tools)
        if "skills" in d:
            out["skills"] = jdump(list(d["skills"] or []))
        if "memory_scope" in d:
            if d["memory_scope"] not in MEM_SCOPE:
                raise Invalid(f"memory_scope must be one of {MEM_SCOPE}")
            out["memory_scope"] = d["memory_scope"]
        if "thinking" in d:
            if d["thinking"] not in THINKING:
                raise Invalid(f"thinking must be one of {THINKING}")
            out["thinking"] = d["thinking"]
        if "effort" in d:
            if d["effort"] not in EFFORT:
                raise Invalid(f"effort must be one of {EFFORT}")
            out["effort"] = d["effort"]
        if "max_steps" in d:
            ms = d["max_steps"]
            if ms is not None and not (1 <= int(ms) <= 200):
                raise Invalid("max_steps must be between 1 and 200")
            out["max_steps"] = None if ms is None else int(ms)
        if "temperature" in d:
            t = d["temperature"]
            if t is not None and not (0 <= float(t) <= 1.5):
                raise Invalid("temperature must be between 0 and 1.5")
            out["temperature"] = None if t is None else float(t)
        return out

    def list(self) -> list[dict]:
        return [self._out(r) for r in self.db.all("SELECT * FROM agents ORDER BY is_default DESC, name")]

    def get(self, agent_id: str) -> dict:
        r = self.db.one("SELECT * FROM agents WHERE id=?", (agent_id,))
        if not r:
            raise NotFound(f"agent {agent_id} not found")
        return self._out(r)

    def find(self, ref: str) -> dict | None:
        """Look up by id or (case-insensitive) name."""
        r = self.db.one("SELECT * FROM agents WHERE id=? OR lower(name)=lower(?)", (ref, ref))
        return self._out(r) if r else None

    def default(self) -> dict:
        r = self.db.one("SELECT * FROM agents WHERE is_default=1 ORDER BY created_at LIMIT 1")
        if not r:
            return self.ensure_default()
        return self._out(r)

    def ensure_default(self) -> dict:
        r = self.db.one("SELECT * FROM agents WHERE is_default=1 LIMIT 1")
        if r:
            return self._out(r)
        return self.create({"name": "General web agent", "description": "Default browsing agent with all tools.",
                            "memory_scope": "global"}, is_default=True)

    def create(self, d: dict, *, is_default: bool = False) -> dict:
        c = self._clean(d)
        if self.db.one("SELECT 1 FROM agents WHERE lower(name)=lower(?)", (c["name"],)):
            raise Conflict(f"an agent named '{c['name']}' already exists")
        aid, t = new_id(), now()
        row = {"id": aid, "description": "", "instructions": "", "start_url": None, "allowed_domains": "[]",
               "allow_private": 0, "tools": None, "skills": "[]", "memory_scope": "global", "thinking": "inherit",
               "effort": "inherit", "max_steps": None, "temperature": None, "profile": None, "workdir": None,
               "is_default": int(is_default), "created_at": t, "updated_at": t, **c}
        cols = ",".join(row)
        self.db.execute(f"INSERT INTO agents ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
        return self.get(aid)

    def update(self, agent_id: str, d: dict) -> dict:
        self.get(agent_id)
        c = self._clean(d, partial=True)
        if "name" in c and self.db.one("SELECT 1 FROM agents WHERE lower(name)=lower(?) AND id<>?", (c["name"], agent_id)):
            raise Conflict(f"an agent named '{c['name']}' already exists")
        c["updated_at"] = now()
        sets = ",".join(f"{k}=?" for k in c)
        self.db.execute(f"UPDATE agents SET {sets} WHERE id=?", [*c.values(), agent_id])
        return self.get(agent_id)

    def delete(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a["is_default"]:
            raise Conflict("the default agent cannot be deleted")
        if self.db.one("SELECT 1 FROM schedules WHERE agent_id=?", (agent_id,)):
            raise Conflict("this agent is used by a schedule; delete or reassign the schedule first")
        self.db.execute("DELETE FROM agents WHERE id=?", (agent_id,))


# =============================================================================== schedules
class ScheduleStore:
    def __init__(self, db: Database):
        self.db = db

    def _out(self, r: sqlite3.Row) -> dict:
        ag = self.db.one("SELECT name FROM agents WHERE id=?", (r["agent_id"],))
        return {"id": r["id"], "name": r["name"], "agent_id": r["agent_id"], "agent_name": ag["name"] if ag else None,
                "task": r["task"], "start_url": r["start_url"], "trigger": jload(r["trigger"], {}),
                "timezone": r["timezone"], "enabled": bool(r["enabled"]), "next_run_at": r["next_run_at"],
                "last_run_at": r["last_run_at"], "last_run_id": r["last_run_id"], "last_status": r["last_status"],
                "run_count": r["run_count"], "created_by": r["created_by"], "created_at": r["created_at"],
                "updated_at": r["updated_at"], "images": jload(r["images"], [])}

    def list(self) -> list[dict]:
        return [self._out(r) for r in self.db.all("SELECT * FROM schedules ORDER BY created_at")]

    def get(self, sid: str) -> dict:
        r = self.db.one("SELECT * FROM schedules WHERE id=?", (sid,))
        if not r:
            raise NotFound(f"schedule {sid} not found")
        return self._out(r)

    def find(self, ref: str) -> dict | None:
        r = self.db.one("SELECT * FROM schedules WHERE id=? OR lower(name)=lower(?)", (ref, ref))
        return self._out(r) if r else None

    def create(self, d: dict) -> dict:
        if not (d.get("name") or "").strip():
            raise Invalid("name is required")
        if not (d.get("task") or "").strip():
            raise Invalid("task is required")
        sid, t = new_id(), now()
        self.db.execute(
            "INSERT INTO schedules (id,name,agent_id,task,start_url,trigger,timezone,enabled,created_by,created_at,updated_at,"
            "images) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, d["name"].strip(), d["agent_id"], d["task"].strip(), d.get("start_url") or None, jdump(d["trigger"]),
             d["timezone"], int(d.get("enabled", True)), d.get("created_by", "user"), t, t,
             jdump(d["images"]) if d.get("images") else None))
        return self.get(sid)

    def update(self, sid: str, d: dict) -> dict:
        self.get(sid)
        allowed = {"name", "agent_id", "task", "start_url", "timezone", "enabled", "trigger", "images"}
        sets, vals = [], []
        for k, v in d.items():
            if k not in allowed:
                continue
            if k == "trigger":
                v = jdump(v)
            elif k == "images":
                v = jdump(v) if v else None
            elif k == "enabled":
                v = int(bool(v))
            sets.append(f"{k}=?")
            vals.append(v)
        sets.append("updated_at=?")
        vals.extend([now(), sid])
        self.db.execute(f"UPDATE schedules SET {','.join(sets)} WHERE id=?", vals)
        return self.get(sid)

    def set_next(self, sid: str, next_run_at: float | None) -> None:
        self.db.execute("UPDATE schedules SET next_run_at=? WHERE id=?", (next_run_at, sid))

    def record_fire(self, sid: str, run_id: str) -> None:
        self.db.execute("UPDATE schedules SET last_run_at=?, last_run_id=?, last_status='queued', "
                        "run_count=run_count+1 WHERE id=?", (now(), run_id, sid))

    def record_result(self, sid: str, status: str) -> None:
        self.db.execute("UPDATE schedules SET last_status=? WHERE id=?", (status, sid))

    def delete(self, sid: str) -> None:
        self.get(sid)
        self.db.execute("DELETE FROM schedules WHERE id=?", (sid,))


# =============================================================================== runs
ACTIVE = ("queued", "running")


class RunStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def summary(r: sqlite3.Row) -> dict:
        res = jload(r["result_json"], None)
        if res is not None and not isinstance(res, str):
            res = jdump(res)
        wall = r["wall_seconds"] or 0.0
        if r["status"] == "running" and r["started_at"]:
            wall = now() - r["started_at"]
        return {"id": r["id"], "task": r["task"], "agent_id": r["agent_id"], "agent_name": r["agent_name"],
                "schedule_id": r["schedule_id"], "trigger": r["trigger"], "status": r["status"],
                "success": None if r["success"] is None else bool(r["success"]), "result": res, "error": r["error"],
                "queued_at": r["queued_at"], "started_at": r["started_at"], "finished_at": r["finished_at"],
                "steps": r["steps"], "prompt_tokens": r["prompt_tokens"], "cached_tokens": r["cached_tokens"],
                "processed_tokens": r["processed_tokens"], "completion_tokens": r["completion_tokens"],
                "llm_seconds": round(r["llm_seconds"] or 0, 2), "tool_seconds": round(r["tool_seconds"] or 0, 2),
                "wall_seconds": round(wall, 2), "thinking": r["thinking"], "effort": r["effort"],
                "current_url": r["current_url"], "last_screenshot": r["last_screenshot"],
                "images": (jload(r["config_json"], None) or {}).get("images", [])}

    def create(self, run_id: str, task: str, *, agent: dict, trigger: str, schedule_id: str | None, config: dict,
               thinking: str, effort: str, run_dir: str) -> dict:
        self.db.execute(
            "INSERT INTO runs (id,task,config_json,status,agent_id,agent_name,schedule_id,trigger,queued_at,thinking,"
            "effort,run_dir) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, task, jdump(config), "queued", agent["id"], agent["name"], schedule_id, trigger, now(),
             thinking, effort, run_dir))
        return self.get(run_id)

    def get(self, run_id: str) -> dict:
        r = self.db.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not r:
            raise NotFound(f"run {run_id} not found")
        return self.summary(r)

    def raw(self, run_id: str) -> sqlite3.Row:
        r = self.db.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not r:
            raise NotFound(f"run {run_id} not found")
        return r

    def list(self, *, status: str | None = None, agent_id: str | None = None, schedule_id: str | None = None,
             q: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        where, params = ["1=1"], []
        if status:
            where.append("status=?")
            params.append(status)
        if agent_id:
            where.append("agent_id=?")
            params.append(agent_id)
        if schedule_id:
            where.append("schedule_id=?")
            params.append(schedule_id)
        if q:
            where.append("(task LIKE ? OR result_json LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        w = " AND ".join(where)
        total = self.db.one(f"SELECT COUNT(*) c FROM runs WHERE {w}", params)["c"]
        rows = self.db.all(f"SELECT * FROM runs WHERE {w} ORDER BY COALESCE(started_at, queued_at) DESC LIMIT ? OFFSET ?",
                           [*params, limit, offset])
        return [self.summary(r) for r in rows], total

    def mark_running(self, run_id: str) -> None:
        self.db.execute("UPDATE runs SET status='running', started_at=? WHERE id=?", (now(), run_id))

    def set_status(self, run_id: str, status: str, error: str | None = None) -> None:
        self.db.execute("UPDATE runs SET status=?, error=COALESCE(?, error) WHERE id=?", (status, error, run_id))

    def bump(self, run_id: str, **kw: Any) -> None:
        """Increment/set live counters while running (steps, tokens, seconds, current_url, last_screenshot)."""
        sets, vals = [], []
        for k, v in kw.items():
            if k in ("current_url", "last_screenshot"):
                sets.append(f"{k}=?")
            else:
                sets.append(f"{k}=COALESCE({k},0)+?")
            vals.append(v)
        self.db.execute(f"UPDATE runs SET {','.join(sets)} WHERE id=?", [*vals, run_id])

    def finish(self, run_id: str, status: str, success: bool, result: Any, error: str | None, totals: dict) -> None:
        self.db.execute(
            "UPDATE runs SET status=?, success=?, result_json=?, error=?, finished_at=?, steps=?, prompt_tokens=?, "
            "cached_tokens=?, processed_tokens=?, completion_tokens=?, llm_seconds=?, tool_seconds=?, wall_seconds=? "
            "WHERE id=?",
            (status, int(success), jdump(result), error, now(), totals["steps"], totals["prompt_tokens"],
             totals["cached_tokens"], totals["processed_tokens"], totals["completion_tokens"], totals["llm_seconds"],
             totals["tool_seconds"], totals["wall_seconds"], run_id))

    def add_step(self, run_id: str, idx: int, kind: str, **f: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO steps (run_id,idx,ts,kind,name,args_json,result_preview,url,think,prompt_tokens,"
            "cached_tokens,processed_tokens,completion_tokens,llm_seconds,prefill_ms,decode_ms,decode_tps,"
            "tool_seconds,ok,screenshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, idx, now(), kind, f.get("name"), None if f.get("args") is None else jdump(f["args"]),
             (f.get("result") or "")[:2000] if f.get("result") is not None else None, f.get("url"),
             None if f.get("think") is None else int(f["think"]), f.get("prompt_tokens"), f.get("cached_tokens"),
             f.get("processed_tokens"), f.get("completion_tokens"), f.get("llm_seconds"), f.get("prefill_ms"),
             f.get("decode_ms"), f.get("decode_tps"), f.get("tool_seconds"),
             None if f.get("ok") is None else int(f["ok"]), f.get("screenshot")))

    def set_step_screenshot(self, run_id: str, idx: int, n: int) -> None:
        self.db.execute("UPDATE steps SET screenshot=? WHERE run_id=? AND idx=?", (n, run_id, idx))

    def steps(self, run_id: str) -> list[dict]:
        out = []
        for r in self.db.all("SELECT * FROM steps WHERE run_id=? ORDER BY idx", (run_id,)):
            out.append({"idx": r["idx"], "kind": r["kind"], "name": r["name"], "args": jload(r["args_json"], None),
                        "result": r["result_preview"], "ok": None if r["ok"] is None else bool(r["ok"]),
                        "url": r["url"], "think": None if r["think"] is None else bool(r["think"]),
                        "prompt_tokens": r["prompt_tokens"], "cached_tokens": r["cached_tokens"],
                        "processed_tokens": r["processed_tokens"], "completion_tokens": r["completion_tokens"],
                        "llm_seconds": r["llm_seconds"], "prefill_ms": r["prefill_ms"], "decode_ms": r["decode_ms"],
                        "decode_tps": r["decode_tps"], "tool_seconds": r["tool_seconds"], "ts": r["ts"],
                        "screenshot": r["screenshot"]})
        return out

    def orphaned_to_failed(self) -> int:
        cur = self.db.execute("UPDATE runs SET status='failed', error='server restarted while the run was active', "
                              "finished_at=? WHERE status IN ('queued','running')", (now(),))
        return cur.rowcount


# =============================================================================== memories
def _fts_query(q: str) -> str | None:
    toks = [t for t in re.findall(r"\w+", q.lower()) if len(t) >= 3][:12]
    return " OR ".join(f'"{t}"*' for t in toks) if toks else None


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _out(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "title": r["title"] or "", "content": r["content"], "tags": jload(r["tags"], []),
                "scope": r["scope"], "pinned": bool(r["pinned"]), "status": r["status"], "source": r["source"],
                "created_at": r["created_at"], "updated_at": r["updated_at"], "last_used_at": r["last_used_at"],
                "use_count": r["use_count"]}

    def _fts_sync(self, mid: str) -> None:
        self.db.execute("DELETE FROM memories_fts WHERE mid=?", (mid,))
        r = self.db.one("SELECT * FROM memories WHERE id=?", (mid,))
        if r and r["status"] == "active":
            self.db.execute("INSERT INTO memories_fts (mid, title, content, tags) VALUES (?,?,?,?)",
                            (mid, r["title"] or "", r["content"], " ".join(jload(r["tags"], []))))

    def get(self, mid: str) -> dict:
        r = self.db.one("SELECT * FROM memories WHERE id=?", (mid,))
        if not r:
            raise NotFound(f"memory {mid} not found")
        return self._out(r)

    def create(self, d: dict) -> dict:
        content = (d.get("content") or "").strip()
        if not content:
            raise Invalid("content is required")
        scope = d.get("scope") or "global"
        if scope != "global" and not scope.startswith("agent:"):
            raise Invalid("scope must be 'global' or 'agent:<agent_id>'")
        status = d.get("status", "active")
        if status not in ("active", "pending"):
            raise Invalid("status must be active or pending")
        mid, t = new_id(), now()
        self.db.execute(
            "INSERT INTO memories (id,title,content,tags,scope,pinned,status,source,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, (d.get("title") or "").strip(), content[:4000], jdump([str(x) for x in d.get("tags") or []]), scope,
             int(bool(d.get("pinned", False))), status, d.get("source", "user"), t, t))
        self._fts_sync(mid)
        return self.get(mid)

    def update(self, mid: str, d: dict) -> dict:
        cur = self.get(mid)
        merged = {**cur, **{k: v for k, v in d.items() if k in ("title", "content", "tags", "scope", "pinned", "status")}}
        if not (merged["content"] or "").strip():
            raise Invalid("content is required")
        self.db.execute("UPDATE memories SET title=?, content=?, tags=?, scope=?, pinned=?, status=?, updated_at=? WHERE id=?",
                        (merged["title"], merged["content"][:4000], jdump(merged["tags"]), merged["scope"],
                         int(bool(merged["pinned"])), merged["status"], now(), mid))
        self._fts_sync(mid)
        return self.get(mid)

    def delete(self, mid: str) -> None:
        self.get(mid)
        self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        self.db.execute("DELETE FROM memories_fts WHERE mid=?", (mid,))

    def list(self, *, q: str | None = None, scope: str | None = None, pinned: bool | None = None,
             status: str | None = None, limit: int = 100) -> list[dict]:
        where, params = ["1=1"], []
        for col, val in (("m.scope", scope), ("m.status", status)):
            if val:
                where.append(f"{col}=?")
                params.append(val)
        if pinned is not None:
            where.append("m.pinned=?")
            params.append(int(pinned))
        w = " AND ".join(where)
        fq = _fts_query(q) if q else None
        if q and fq:
            rows = self.db.all(
                f"SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.mid WHERE memories_fts MATCH ? AND {w} "
                f"ORDER BY bm25(memories_fts) LIMIT ?", [fq, *params, limit])
        elif q:
            rows = self.db.all(f"SELECT m.* FROM memories m WHERE {w} AND (m.content LIKE ? OR m.title LIKE ?) "
                               f"ORDER BY m.updated_at DESC LIMIT ?", [*params, f"%{q}%", f"%{q}%", limit])
        else:
            rows = self.db.all(f"SELECT m.* FROM memories m WHERE {w} ORDER BY m.pinned DESC, m.updated_at DESC LIMIT ?",
                               [*params, limit])
        return [self._out(r) for r in rows]

    def relevant(self, task: str, scopes: list[str], k: int, max_chars: int = 1800) -> list[dict]:
        """Pinned memories in scope + top-k full-text matches for the task. Marks them used."""
        if not scopes:
            return []
        marks = ",".join("?" * len(scopes))
        picked = [self._out(r) for r in self.db.all(
            f"SELECT * FROM memories WHERE pinned=1 AND status='active' AND scope IN ({marks}) ORDER BY updated_at DESC",
            scopes)]
        seen = {m["id"] for m in picked}
        fq = _fts_query(task)
        if fq and k > 0:
            for r in self.db.all(
                    f"SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.mid WHERE memories_fts MATCH ? "
                    f"AND m.status='active' AND m.scope IN ({marks}) ORDER BY bm25(memories_fts) LIMIT ?",
                    [fq, *scopes, k + len(seen)]):
                if r["id"] not in seen and len([m for m in picked if not m["pinned"]]) < k:
                    picked.append(self._out(r))
                    seen.add(r["id"])
        out, used = [], 0
        for m in picked:
            used += len(m["content"]) + len(m["title"])
            if used > max_chars:
                break
            out.append(m)
        for m in out:
            self.db.execute("UPDATE memories SET last_used_at=?, use_count=use_count+1 WHERE id=?", (now(), m["id"]))
        return out


# =============================================================================== conversations
class ProjectStore:
    """A named group of chats with an optional working folder for the assistant's terminal."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _folder(folder: str | None) -> str | None:
        f = (folder or "").strip()
        if not f:
            return None
        p = Path(f).expanduser()
        if not p.is_dir():
            raise Invalid(f"folder '{f}' does not exist or is not a directory")
        return str(p.resolve())

    @staticmethod
    def _name(name: str | None) -> str:
        n = (name or "").strip()[:80]
        if not n:
            raise Invalid("project name is required")
        return n

    def list(self) -> list[dict]:
        return [dict(r) for r in self.db.all(
            "SELECT id, name, folder, created_at, updated_at, (SELECT COUNT(*) FROM conversations c WHERE c.project_id=projects.id) "
            "AS chat_count FROM projects ORDER BY name COLLATE NOCASE")]

    def get(self, pid: str) -> dict:
        r = self.db.one("SELECT id, name, folder, created_at, updated_at FROM projects WHERE id=?", (pid,))
        if not r:
            raise NotFound(f"project {pid} not found")
        return dict(r)

    def exists(self, pid: str) -> bool:
        return self.db.one("SELECT 1 FROM projects WHERE id=?", (pid,)) is not None

    def create(self, name: str, folder: str | None = None) -> dict:
        pid, t = new_id(), now()
        self.db.execute("INSERT INTO projects (id,name,folder,created_at,updated_at) VALUES (?,?,?,?,?)",
                        (pid, self._name(name), self._folder(folder), t, t))
        return self.get(pid)

    def update(self, pid: str, name: str | None, folder: str | None) -> dict:
        self.get(pid)
        self.db.execute("UPDATE projects SET name=?, folder=?, updated_at=? WHERE id=?",
                        (self._name(name), self._folder(folder), now(), pid))
        return self.get(pid)

    def delete(self, pid: str) -> None:
        self.get(pid)
        self.db.execute("UPDATE conversations SET project_id=NULL WHERE project_id=?", (pid,))   # chats are kept
        self.db.execute("DELETE FROM projects WHERE id=?", (pid,))


class ConversationStore:
    def __init__(self, db: Database):
        self.db = db

    def list(self) -> list[dict]:
        rows = self.db.all("SELECT c.id, c.title, c.updated_at, c.project_id, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id "
                           "AND m.role IN ('user','assistant')) AS n FROM conversations c ORDER BY c.updated_at DESC")
        return [{"id": r["id"], "title": r["title"], "updated_at": r["updated_at"], "message_count": r["n"],
                 "project_id": r["project_id"]} for r in rows]

    def create(self, title: str | None = None, project_id: str | None = None) -> dict:
        if project_id and not self.db.one("SELECT 1 FROM projects WHERE id=?", (project_id,)):
            raise NotFound(f"project {project_id} not found")
        cid, t = new_id(), now()
        self.db.execute("INSERT INTO conversations (id,title,created_at,updated_at,project_id) VALUES (?,?,?,?,?)",
                        (cid, title or "New chat", t, t, project_id or None))
        return {"id": cid, "title": title or "New chat", "updated_at": t, "message_count": 0, "project_id": project_id or None}

    def project_of(self, cid: str) -> dict | None:
        r = self.db.one("SELECT p.id, p.name, p.folder FROM conversations c JOIN projects p ON p.id=c.project_id "
                        "WHERE c.id=?", (cid,))
        return dict(r) if r else None

    def move(self, cid: str, project_id: str | None) -> None:
        if not self.exists(cid):
            raise NotFound(f"conversation {cid} not found")
        if project_id and not self.db.one("SELECT 1 FROM projects WHERE id=?", (project_id,)):
            raise NotFound(f"project {project_id} not found")
        self.db.execute("UPDATE conversations SET project_id=? WHERE id=?", (project_id or None, cid))

    def exists(self, cid: str) -> bool:
        return self.db.one("SELECT 1 FROM conversations WHERE id=?", (cid,)) is not None

    def rename(self, cid: str, title: str) -> None:
        if not self.exists(cid):
            raise NotFound(f"conversation {cid} not found")
        self.db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title.strip()[:120] or "Chat", now(), cid))

    def delete(self, cid: str) -> None:
        if not self.exists(cid):
            raise NotFound(f"conversation {cid} not found")
        self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))

    @staticmethod
    def _msg(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "role": r["role"], "content": r["content"] or "", "reasoning": r["reasoning"],
                "tool_calls": jload(r["tool_calls"], None), "tool_call_id": r["tool_call_id"],
                "action_id": r["action_id"], "run_id": r["run_id"], "stats": jload(r["stats"], None),
                "images": jload(r["images"], []), "created_at": r["created_at"]}

    def get(self, cid: str) -> dict:
        c = self.db.one("SELECT * FROM conversations WHERE id=?", (cid,))
        if not c:
            raise NotFound(f"conversation {cid} not found")
        msgs = [self._msg(r) for r in self.db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY seq", (cid,))]
        return {"id": cid, "title": c["title"], "project_id": c["project_id"], "messages": msgs}

    def append(self, cid: str, role: str, content: str = "", *, reasoning: str | None = None,
               tool_calls: list | None = None, tool_call_id: str | None = None, action_id: str | None = None,
               run_id: str | None = None, stats: dict | None = None, images: list[str] | None = None) -> dict:
        seq = self.db.one("SELECT COALESCE(MAX(seq),0)+1 AS n FROM messages WHERE conversation_id=?", (cid,))["n"]
        mid, t = new_id(), now()
        self.db.execute(
            "INSERT INTO messages (id,conversation_id,seq,role,content,reasoning,tool_calls,tool_call_id,action_id,run_id,"
            "stats,images,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, cid, seq, role, content, reasoning, None if tool_calls is None else jdump(tool_calls), tool_call_id,
             action_id, run_id, None if stats is None else jdump(stats), jdump(images) if images else None, t))
        self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (t, cid))
        return self._msg(self.db.one("SELECT * FROM messages WHERE id=?", (mid,)))


# =============================================================================== approvals
class ActionStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _out(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "kind": r["kind"], "summary": r["summary"], "payload": jload(r["payload"], {}),
                "status": r["status"], "created_by": r["created_by"], "conversation_id": r["conversation_id"],
                "run_id": r["run_id"], "created_at": r["created_at"], "decided_at": r["decided_at"],
                "result": jload(r["result"], None)}

    def create(self, kind: str, summary: str, payload: dict, *, created_by: str = "assistant",
               conversation_id: str | None = None, run_id: str | None = None) -> dict:
        aid = new_id()
        self.db.execute("INSERT INTO pending_actions (id,kind,summary,payload,status,created_by,conversation_id,run_id,"
                        "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (aid, kind, summary, jdump(payload), "pending", created_by, conversation_id, run_id, now()))
        return self.get(aid)

    def get(self, aid: str) -> dict:
        r = self.db.one("SELECT * FROM pending_actions WHERE id=?", (aid,))
        if not r:
            raise NotFound(f"action {aid} not found")
        return self._out(r)

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        if status:
            rows = self.db.all("SELECT * FROM pending_actions WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
        else:
            rows = self.db.all("SELECT * FROM pending_actions ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._out(r) for r in rows]

    def count_pending(self) -> int:
        return self.db.one("SELECT COUNT(*) c FROM pending_actions WHERE status='pending'")["c"]

    def decide(self, aid: str, status: str, result: Any = None, payload: dict | None = None) -> dict:
        if payload is not None:
            self.db.execute("UPDATE pending_actions SET payload=? WHERE id=?", (jdump(payload), aid))
        self.db.execute("UPDATE pending_actions SET status=?, decided_at=?, result=? WHERE id=?",
                        (status, now(), jdump(result), aid))
        return self.get(aid)

"""SQLite storage. One shared connection (WAL, autocommit) guarded by a lock; writes are tiny."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT DEFAULT '', instructions TEXT DEFAULT '',
  start_url TEXT, allowed_domains TEXT DEFAULT '[]', allow_private INTEGER DEFAULT 0,
  tools TEXT, skills TEXT DEFAULT '[]', memory_scope TEXT DEFAULT 'agent',
  thinking TEXT DEFAULT 'inherit', effort TEXT DEFAULT 'inherit', max_steps INTEGER, temperature REAL,
  profile TEXT, is_default INTEGER DEFAULT 0, created_at REAL, updated_at REAL, workdir TEXT
);
CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, agent_id TEXT NOT NULL, task TEXT NOT NULL, start_url TEXT,
  trigger TEXT NOT NULL, timezone TEXT NOT NULL, enabled INTEGER DEFAULT 1,
  next_run_at REAL, last_run_at REAL, last_run_id TEXT, last_status TEXT, run_count INTEGER DEFAULT 0,
  created_by TEXT DEFAULT 'user', created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, task TEXT NOT NULL, config_json TEXT, status TEXT NOT NULL,
  agent_id TEXT, agent_name TEXT, schedule_id TEXT, trigger TEXT DEFAULT 'manual',
  queued_at REAL, started_at REAL, finished_at REAL, success INTEGER, result_json TEXT, error TEXT,
  steps INTEGER DEFAULT 0, prompt_tokens INTEGER DEFAULT 0, cached_tokens INTEGER DEFAULT 0,
  processed_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
  llm_seconds REAL DEFAULT 0, tool_seconds REAL DEFAULT 0, wall_seconds REAL DEFAULT 0,
  thinking TEXT, effort TEXT, current_url TEXT, last_screenshot INTEGER, run_dir TEXT
);
CREATE INDEX IF NOT EXISTS runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS steps (
  run_id TEXT NOT NULL, idx INTEGER NOT NULL, ts REAL, kind TEXT, name TEXT, args_json TEXT, result_preview TEXT,
  url TEXT, think INTEGER, prompt_tokens INTEGER, cached_tokens INTEGER, processed_tokens INTEGER,
  completion_tokens INTEGER, llm_seconds REAL, prefill_ms REAL, decode_ms REAL, decode_tps REAL,
  tool_seconds REAL, ok INTEGER, screenshot INTEGER, PRIMARY KEY (run_id, idx)
);
CREATE TABLE IF NOT EXISTS run_events (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL, type TEXT, data TEXT, PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, title TEXT DEFAULT '', content TEXT NOT NULL, tags TEXT DEFAULT '[]',
  scope TEXT DEFAULT 'global', pinned INTEGER DEFAULT 0, status TEXT DEFAULT 'active', source TEXT DEFAULT 'user',
  created_at REAL, updated_at REAL, last_used_at REAL, use_count INTEGER DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(mid UNINDEXED, title, content, tags);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, folder TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, title TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL, content TEXT,
  reasoning TEXT, tool_calls TEXT, tool_call_id TEXT, action_id TEXT, run_id TEXT, stats TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conversation_id, seq);
CREATE TABLE IF NOT EXISTS conversation_summaries (
  conversation_id TEXT PRIMARY KEY, upto_seq INTEGER NOT NULL DEFAULT 0, pruned_upto INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT '', at_seq INTEGER NOT NULL DEFAULT 0, updated_at REAL
);
CREATE TABLE IF NOT EXISTS pending_actions (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, summary TEXT, payload TEXT, status TEXT DEFAULT 'pending',
  created_by TEXT, conversation_id TEXT, run_id TEXT, created_at REAL, decided_at REAL, result TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS connectors (
  name TEXT PRIMARY KEY, type TEXT NOT NULL, config TEXT DEFAULT '{}', enabled INTEGER DEFAULT 1,
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS telegram_inbox (
  id TEXT PRIMARY KEY, ts REAL, connector TEXT, chat_id INTEGER, user_id INTEGER, username TEXT, name TEXT,
  kind TEXT DEFAULT 'text', text TEXT DEFAULT '', file_name TEXT DEFAULT '', uploads TEXT DEFAULT '[]',
  status TEXT DEFAULT 'accepted', note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS telegram_inbox_ts ON telegram_inbox(ts);
CREATE TABLE IF NOT EXISTS variables (
  name TEXT PRIMARY KEY, value TEXT NOT NULL, secret INTEGER DEFAULT 0, description TEXT DEFAULT '',
  domains TEXT DEFAULT '[]', created_at REAL, updated_at REAL
);
"""


def now() -> float:
    return time.time()


def new_id(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


def jdump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def jload(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            fresh_inbox = not self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='telegram_inbox'").fetchone()
            self.conn.executescript(SCHEMA)
            self._migrate()
            if fresh_inbox:
                self._backfill_inbox()

    def _migrate(self) -> None:
        """Additive column migrations for databases created by older versions."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(messages)")}
        if "images" not in cols:
            self.conn.execute("ALTER TABLE messages ADD COLUMN images TEXT")
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(agents)")}
        if "workdir" not in cols:
            self.conn.execute("ALTER TABLE agents ADD COLUMN workdir TEXT")
        if "model" not in cols:
            self.conn.execute("ALTER TABLE agents ADD COLUMN model TEXT")
        if "state" not in cols:
            self.conn.execute("ALTER TABLE agents ADD COLUMN state TEXT")
            self.conn.execute("ALTER TABLE agents ADD COLUMN state_updated_at REAL")
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(conversations)")}
        if "project_id" not in cols:
            self.conn.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(schedules)")}
        if "images" not in cols:
            self.conn.execute("ALTER TABLE schedules ADD COLUMN images TEXT")

    def _backfill_inbox(self) -> None:
        """One-time: seed the Telegram inbox from user messages already stored in the Telegram conversations."""
        rows = self.conn.execute(
            "SELECT m.id, m.content, m.images, m.created_at, c.title FROM messages m JOIN conversations c "
            "ON c.id=m.conversation_id WHERE c.title LIKE 'Telegram/%' AND m.role='user'").fetchall()
        for r in rows:
            mt = re.match(r"Telegram/(.+?) (-?\d+)", r["title"] or "")
            ups = jload(r["images"], []) if r["images"] else []
            self.conn.execute(
                "INSERT OR IGNORE INTO telegram_inbox (id,ts,connector,user_id,chat_id,kind,text,uploads,status) "
                "VALUES (?,?,?,?,?,?,?,?,'accepted')",
                (r["id"], r["created_at"], mt.group(1) if mt else "", int(mt.group(2)) if mt else None,
                 int(mt.group(2)) if mt else None, "photo" if ups else "text", r["content"] or "", jdump(ups)))

    def execute(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, tuple(params))

    def one(self, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def all(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

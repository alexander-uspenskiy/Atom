"""In-process event bus: persisted per-run event log (replayable) + live subscribers + global feed."""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from .db import Database, jdump, jload

EPHEMERAL = {"token"}          # live only, never stored or replayed
PING = {"type": "_ping"}


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self._run_subs: dict[str, set[asyncio.Queue]] = {}
        self._global_subs: set[asyncio.Queue] = set()
        self._seq: dict[str, int] = {}

    # ---------- publish ----------
    def _next_seq(self, run_id: str) -> int:
        if run_id not in self._seq:
            row = self.db.one("SELECT COALESCE(MAX(seq), 0) AS m FROM run_events WHERE run_id=?", (run_id,))
            self._seq[run_id] = int(row["m"])
        self._seq[run_id] += 1
        return self._seq[run_id]

    def publish_run(self, run_id: str, type: str, **data: Any) -> dict:
        ev = {"seq": self._next_seq(run_id), "ts": time.time(), "run_id": run_id, "type": type, **data}
        if type not in EPHEMERAL:
            self.db.execute("INSERT OR REPLACE INTO run_events (run_id, seq, ts, type, data) VALUES (?,?,?,?,?)",
                            (run_id, ev["seq"], ev["ts"], type, jdump(data)))
        for q in list(self._run_subs.get(run_id, ())):
            q.put_nowait(ev)
        return ev

    def publish_global(self, type: str, **data: Any) -> None:
        ev = {"ts": time.time(), "type": type, **data}
        for q in list(self._global_subs):
            q.put_nowait(ev)

    # ---------- subscribe ----------
    def stored_events(self, run_id: str, after_seq: int = 0) -> list[dict]:
        rows = self.db.all("SELECT seq, ts, type, data FROM run_events WHERE run_id=? AND seq>? ORDER BY seq",
                           (run_id, after_seq))
        return [{"seq": r["seq"], "ts": r["ts"], "run_id": run_id, "type": r["type"], **(jload(r["data"], {}))}
                for r in rows]

    async def stream_run(self, run_id: str, *, is_finished: bool) -> AsyncIterator[dict]:
        """Replay stored events, then stream live ones until `run_finished` (or forever heartbeat if not)."""
        q: asyncio.Queue = asyncio.Queue()
        self._run_subs.setdefault(run_id, set()).add(q)
        try:
            last = 0
            for ev in self.stored_events(run_id):
                last = ev["seq"]
                yield ev
                if ev["type"] == "run_finished":
                    return
            if is_finished and last:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield PING
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield ev
                if ev["type"] == "run_finished":
                    return
        finally:
            subs = self._run_subs.get(run_id)
            if subs:
                subs.discard(q)
                if not subs:
                    self._run_subs.pop(run_id, None)

    async def stream_global(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._global_subs.add(q)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield PING
        finally:
            self._global_subs.discard(q)

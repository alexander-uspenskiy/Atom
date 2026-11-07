"""Usage statistics for the dashboard (tokens in/out, cache hit rate, timing, per-agent, per-day)."""
from __future__ import annotations

import time
from typing import Any

from .db import Database
from .stores import RunStore


def _f(v: Any, nd: int = 2) -> float:
    return round(float(v or 0), nd)


def summary(db: Database, runs: RunStore, days: int = 7) -> dict:
    days = max(1, min(int(days), 365))
    cutoff = time.time() - days * 86400
    ts = "COALESCE(started_at, queued_at)"
    r = db.one(
        f"""SELECT COUNT(*) total,
            SUM(status='done' AND success=1) done, SUM(status='failed') failed, SUM(status='budget') budget,
            SUM(status='stopped') stopped, SUM(status IN ('done','failed','budget','stopped')) finished,
            SUM(prompt_tokens) inp, SUM(cached_tokens) cached, SUM(processed_tokens) processed,
            SUM(completion_tokens) outp, AVG(CASE WHEN finished_at IS NOT NULL THEN wall_seconds END) avg_wall,
            SUM(llm_seconds) llm_s, SUM(steps) steps
            FROM runs WHERE {ts} >= ?""", (cutoff,))
    st = db.one(
        f"""SELECT SUM(s.completion_tokens) c, SUM(s.decode_ms) dms, SUM(s.processed_tokens) p, SUM(s.prefill_ms) pms
            FROM steps s JOIN runs r ON r.id = s.run_id
            WHERE s.kind='llm' AND s.decode_ms > 0 AND COALESCE(r.started_at, r.queued_at) >= ?""", (cutoff,))
    by_day = [{"day": x["day"], "runs": x["runs"], "input": x["inp"] or 0, "cached": x["cached"] or 0,
               "output": x["outp"] or 0, "llm_seconds": _f(x["llm_s"])}
              for x in db.all(
        f"""SELECT date({ts}, 'unixepoch', 'localtime') day, COUNT(*) runs, SUM(prompt_tokens) inp,
            SUM(cached_tokens) cached, SUM(completion_tokens) outp, SUM(llm_seconds) llm_s
            FROM runs WHERE {ts} >= ? GROUP BY day ORDER BY day""", (cutoff,))]
    by_agent = [{"agent_id": x["agent_id"], "agent_name": x["agent_name"], "runs": x["runs"],
                 "success_rate": _f((x["ok"] or 0) / x["fin"], 3) if x["fin"] else 0.0, "input": x["inp"] or 0,
                 "output": x["outp"] or 0, "avg_wall_s": _f(x["avg_wall"])}
                for x in db.all(
        f"""SELECT agent_id, agent_name, COUNT(*) runs, SUM(status='done' AND success=1) ok,
            SUM(status IN ('done','failed','budget','stopped')) fin, SUM(prompt_tokens) inp,
            SUM(completion_tokens) outp, AVG(CASE WHEN finished_at IS NOT NULL THEN wall_seconds END) avg_wall
            FROM runs WHERE {ts} >= ? GROUP BY agent_id ORDER BY runs DESC""", (cutoff,))]
    slow = [RunStore.summary(x) for x in db.all(
        f"SELECT * FROM runs WHERE {ts} >= ? AND finished_at IS NOT NULL ORDER BY wall_seconds DESC LIMIT 5", (cutoff,))]
    chat = db.one(
        """SELECT COUNT(*) n, SUM(json_extract(stats,'$.prompt_tokens')) i, SUM(json_extract(stats,'$.cached_tokens')) c,
           SUM(json_extract(stats,'$.completion_tokens')) o FROM messages
           WHERE role='assistant' AND stats IS NOT NULL AND created_at >= ?""", (cutoff,))
    finished = r["finished"] or 0
    inp, cached = r["inp"] or 0, r["cached"] or 0
    return {
        "days": days,
        "runs": {"total": r["total"] or 0, "done": r["done"] or 0, "failed": r["failed"] or 0,
                 "budget": r["budget"] or 0, "stopped": r["stopped"] or 0,
                 "success_rate": _f((r["done"] or 0) / finished, 3) if finished else 0.0},
        "tokens": {"input": inp, "cached": cached, "processed": r["processed"] or 0, "output": r["outp"] or 0,
                   "cache_hit_rate": _f(cached / inp, 3) if inp else 0.0},
        "timing": {"avg_wall_s": _f(r["avg_wall"]),
                   "avg_llm_s_per_step": _f((r["llm_s"] or 0) / r["steps"]) if r["steps"] else 0.0,
                   "avg_decode_tps": _f((st["c"] or 0) / ((st["dms"] or 0) / 1000), 1) if st["dms"] else 0.0,
                   "avg_prefill_tps": _f((st["p"] or 0) / ((st["pms"] or 0) / 1000), 1) if st["pms"] else 0.0},
        "by_day": by_day, "by_agent": by_agent, "slowest_runs": slow,
        "chat": {"messages": chat["n"] or 0, "input": chat["i"] or 0, "cached": chat["c"] or 0, "output": chat["o"] or 0},
    }

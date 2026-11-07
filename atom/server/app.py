"""FastAPI application: REST + SSE API for the Atom dashboard (see docs/DASHBOARD_API.md)."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .. import stats as stats_mod
from ..assistant import Assistant
from ..config import ROOT
from ..events import PING
from ..llm import LLMError
from ..scheduler import describe, normalize_trigger, preview
from ..services import Services
from ..settings_store import SettingsError
from ..stores import Conflict, Invalid, NotFound
from ..tools import build_tools

VERSION = "0.2.0"
DIST = ROOT / "web" / "dist"


def sse_line(ev: dict) -> str:
    if ev is PING or ev.get("type") == "_ping":
        return ": ping\n\n"
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


async def sse_stream(gen: AsyncIterator[dict], request: Request) -> AsyncIterator[str]:
    """Pump `gen` to the client, and stop it promptly when the client goes away.

    Relying on a failed write is not enough: while the model is mid-generation nothing may be written for a
    while, and some server/ASGI combinations silently drop writes after a disconnect. So we poll for the
    disconnect ourselves and close `gen`, which cancels the model call and frees the llama-server slot.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for ev in gen:
                await queue.put(("ev", ev))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await queue.put(("ev", {"type": "error", "detail": f"{type(e).__name__}: {e}"}))
        finally:
            await queue.put(("end", None))

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                kind, ev = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                continue
            if kind == "end":
                break
            yield sse_line(ev)
    finally:
        task.cancel()                                   # cancels gen -> LLM stream -> llama-server stops generating
        await asyncio.gather(task, return_exceptions=True)
        aclose = getattr(gen, "aclose", None)
        if aclose:
            try:
                await aclose()
            except Exception:  # noqa: BLE001
                pass


def sse_response(gen: AsyncIterator[dict], request: Request) -> StreamingResponse:
    return StreamingResponse(sse_stream(gen, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


def create_app(services: Services | None = None, *, start_scheduler: bool = True) -> FastAPI:
    owns = services is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or Services()
        app.state.svc = svc
        svc.assistant = Assistant(svc)
        await svc.startup(scheduler=start_scheduler)
        ticker = asyncio.create_task(_status_ticker(app))
        try:
            yield
        finally:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
            if owns:
                await svc.shutdown()

    app = FastAPI(title="Atom", version=VERSION, lifespan=lifespan)

    # ------------------------------------------------------------------ errors
    for exc, code in ((NotFound, 404), (Invalid, 422), (SettingsError, 422), (Conflict, 409)):
        def make(c: int):
            async def handler(request: Request, e: Exception):
                return JSONResponse({"detail": str(e.args[0]) if e.args else str(e)}, status_code=c)
            return handler
        app.add_exception_handler(exc, make(code))

    @app.exception_handler(LLMError)
    async def llm_error(request: Request, e: LLMError):
        return JSONResponse({"detail": str(e)}, status_code=502)

    def svc_of(request: Request) -> Services:
        return request.app.state.svc

    # ------------------------------------------------------------------ system
    async def status_payload(svc: Services) -> dict:
        eff = svc.settings.effective()
        try:
            healthy = await asyncio.wait_for(svc.llm.healthy(), timeout=2.5)
            slots = await asyncio.wait_for(svc.llm.slots(), timeout=2.5) if healthy else []
        except Exception:  # noqa: BLE001
            healthy, slots = False, []
        roles = {eff.agent_slot: "agent", eff.extract_slot: "extract", eff.chat_slot: "chat"}
        return {"version": VERSION,
                "llm": {"healthy": healthy, "base_url": eff.llm_base_url, "model": eff.llm_model,
                        "slots": [{**s, "role": roles.get(s["id"], "other")} for s in slots]},
                "runs": {"running": svc.run_manager.running_ids(), "queued": svc.run_manager.queued_count(),
                         "max_concurrent": eff.max_concurrent_runs},
                "scheduler": {"running": bool(svc.scheduler.sched and svc.scheduler.sched.running),
                              "jobs": svc.scheduler.job_count()},
                "pending_actions": svc.action_store.count_pending()}

    async def _status_ticker(app: FastAPI) -> None:
        while True:
            try:
                svc: Services = app.state.svc
                svc.bus.publish_global("status", status=await status_payload(svc))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(5)

    @app.get("/api/status")
    async def get_status(request: Request):
        return await status_payload(svc_of(request))

    @app.get("/api/events")
    async def global_events(request: Request):
        svc = svc_of(request)

        async def gen():
            yield {"type": "status", "status": await status_payload(svc)}
            async for ev in svc.bus.stream_global():
                yield ev
        return sse_response(gen(), request)

    # ------------------------------------------------------------------ settings
    @app.get("/api/settings")
    async def get_settings(request: Request):
        return svc_of(request).settings.payload()

    @app.put("/api/settings")
    async def put_settings(request: Request, body: dict = Body(...)):
        svc = svc_of(request)
        svc.settings.update(body.get("values") or {})
        return svc.settings.payload()

    # ------------------------------------------------------------------ agents
    @app.get("/api/tools")
    async def list_tools():
        return [{"name": t.name, "description": t.description, "side_effect": t.side_effect}
                for t in build_tools().values()]

    @app.get("/api/agents")
    async def list_agents(request: Request):
        return svc_of(request).agents.list()

    @app.post("/api/agents", status_code=201)
    async def create_agent(request: Request, body: dict = Body(...)):
        return svc_of(request).agents.create(body)

    @app.get("/api/agents/{agent_id}")
    async def get_agent(request: Request, agent_id: str):
        return svc_of(request).agents.get(agent_id)

    @app.put("/api/agents/{agent_id}")
    async def update_agent(request: Request, agent_id: str, body: dict = Body(...)):
        return svc_of(request).agents.update(agent_id, body)

    @app.delete("/api/agents/{agent_id}", status_code=204)
    async def delete_agent(request: Request, agent_id: str):
        svc_of(request).agents.delete(agent_id)

    @app.post("/api/agents/{agent_id}/run", status_code=202)
    async def run_agent(request: Request, agent_id: str, body: dict = Body(...)):
        svc = svc_of(request)
        task = (body.get("task") or "").strip()
        if not task:
            raise Invalid("task is required")
        agent = svc.agents.get(agent_id)
        run = svc.run_manager.enqueue(task, agent, trigger="manual", start_url=body.get("start_url") or None,
                                      overrides=body.get("overrides") or {})
        return {"run_id": run["id"]}

    # ------------------------------------------------------------------ runs
    @app.get("/api/runs")
    async def list_runs(request: Request, status: str | None = None, agent_id: str | None = None,
                        schedule_id: str | None = None, q: str | None = None, limit: int = Query(50, le=200),
                        offset: int = 0):
        items, total = svc_of(request).runs.list(status=status, agent_id=agent_id, schedule_id=schedule_id, q=q,
                                                  limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str):
        svc = svc_of(request)
        return {"run": svc.runs.get(run_id), "steps": svc.runs.steps(run_id), "events_url": f"/api/runs/{run_id}/events"}

    @app.post("/api/runs/{run_id}/stop")
    async def stop_run(request: Request, run_id: str):
        return await svc_of(request).run_manager.stop(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def run_events(request: Request, run_id: str):
        svc = svc_of(request)
        row = svc.runs.get(run_id)
        finished = row["status"] not in ("queued", "running")
        return sse_response(svc.bus.stream_run(run_id, is_finished=finished), request)

    @app.get("/api/runs/{run_id}/shots/{n}.jpg")
    async def run_shot(request: Request, run_id: str, n: int):
        svc = svc_of(request)
        svc.runs.get(run_id)
        path = svc.settings.effective().runs_dir / run_id / "shots" / f"{n}.jpg"
        if not path.exists():
            raise NotFound("screenshot not found")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/api/runs/{run_id}/trace.zip")
    async def run_trace(request: Request, run_id: str):
        svc = svc_of(request)
        svc.runs.get(run_id)
        path = svc.settings.effective().runs_dir / run_id / "trace.zip"
        if not path.exists():
            raise NotFound("trace not available (run still active or never started)")
        return FileResponse(path, media_type="application/zip", filename=f"{run_id}-trace.zip")

    # ------------------------------------------------------------------ schedules
    @app.get("/api/schedules")
    async def list_schedules(request: Request):
        return svc_of(request).schedules.list()

    @app.post("/api/schedules", status_code=201)
    async def create_schedule(request: Request, body: dict = Body(...)):
        return svc_of(request).scheduler.create({**body, "created_by": "user"})

    @app.post("/api/schedules/preview")
    async def preview_schedule(request: Request, body: dict = Body(...)):
        tz = body.get("timezone") or svc_of(request).settings.effective().timezone
        try:
            trig = normalize_trigger(body.get("trigger") or {}, tz)
        except Invalid as e:      # 200 + error: a half-typed cron is normal while the user edits, not a failure
            return {"next": [], "description": "", "error": str(e.args[0])}
        return {"next": preview(trig, tz, int(body.get("count") or 5)), "description": describe(trig, tz), "error": None}

    @app.get("/api/schedules/{sid}")
    async def get_schedule(request: Request, sid: str):
        return svc_of(request).schedules.get(sid)

    @app.put("/api/schedules/{sid}")
    async def update_schedule(request: Request, sid: str, body: dict = Body(...)):
        return svc_of(request).scheduler.update(sid, body)

    @app.delete("/api/schedules/{sid}", status_code=204)
    async def delete_schedule(request: Request, sid: str):
        svc_of(request).scheduler.delete(sid)

    @app.post("/api/schedules/{sid}/run", status_code=202)
    async def run_schedule(request: Request, sid: str):
        run = await svc_of(request).scheduler.trigger_now(sid, trigger="manual")
        return {"run_id": run["id"]}

    @app.post("/api/schedules/{sid}/toggle")
    async def toggle_schedule(request: Request, sid: str, body: dict = Body(...)):
        return svc_of(request).scheduler.toggle(sid, bool(body.get("enabled")))

    # ------------------------------------------------------------------ memory
    @app.get("/api/memories")
    async def list_memories(request: Request, q: str | None = None, scope: str | None = None,
                            pinned: bool | None = None, status: str | None = None, limit: int = Query(100, le=500)):
        return svc_of(request).memory.list(q=q, scope=scope, pinned=pinned, status=status, limit=limit)

    @app.post("/api/memories", status_code=201)
    async def create_memory(request: Request, body: dict = Body(...)):
        return svc_of(request).memory.create({**body, "source": body.get("source") or "user"})

    @app.put("/api/memories/{mid}")
    async def update_memory(request: Request, mid: str, body: dict = Body(...)):
        return svc_of(request).memory.update(mid, body)

    @app.delete("/api/memories/{mid}", status_code=204)
    async def delete_memory(request: Request, mid: str):
        svc_of(request).memory.delete(mid)

    # ------------------------------------------------------------------ skills
    @app.get("/api/skills")
    async def list_skills(request: Request):
        return svc_of(request).skills.list()

    @app.post("/api/skills", status_code=201)
    async def create_skill(request: Request, body: dict = Body(...)):
        return svc_of(request).skills.create({**body, "created_by": "user"})

    @app.get("/api/skills/{name}")
    async def get_skill(request: Request, name: str):
        return svc_of(request).skills.get(name)

    @app.put("/api/skills/{name}")
    async def update_skill(request: Request, name: str, body: dict = Body(...)):
        return svc_of(request).skills.update(name, body)

    @app.delete("/api/skills/{name}", status_code=204)
    async def delete_skill(request: Request, name: str):
        svc_of(request).skills.delete(name)

    # ------------------------------------------------------------------ approvals
    @app.get("/api/actions")
    async def list_actions(request: Request, status: str | None = None):
        return svc_of(request).action_store.list(status)

    @app.post("/api/actions/{aid}/approve")
    async def approve_action(request: Request, aid: str, body: dict = Body(default={})):
        return await svc_of(request).executor.approve(aid, body.get("payload"))

    @app.post("/api/actions/{aid}/reject")
    async def reject_action(request: Request, aid: str):
        return await svc_of(request).executor.reject(aid)

    # ------------------------------------------------------------------ chat
    @app.get("/api/conversations")
    async def list_conversations(request: Request):
        return svc_of(request).conversations.list()

    @app.post("/api/conversations", status_code=201)
    async def create_conversation(request: Request, body: dict = Body(default={})):
        return svc_of(request).conversations.create(body.get("title"))

    @app.get("/api/conversations/{cid}")
    async def get_conversation(request: Request, cid: str):
        return svc_of(request).conversations.get(cid)

    @app.put("/api/conversations/{cid}")
    async def rename_conversation(request: Request, cid: str, body: dict = Body(...)):
        svc = svc_of(request)
        svc.conversations.rename(cid, body.get("title") or "Chat")
        return {"id": cid, "title": body.get("title")}

    @app.delete("/api/conversations/{cid}", status_code=204)
    async def delete_conversation(request: Request, cid: str):
        svc_of(request).conversations.delete(cid)

    @app.post("/api/conversations/{cid}/messages")
    async def post_message(request: Request, cid: str, body: dict = Body(...)):
        svc = svc_of(request)
        content = (body.get("content") or "").strip()
        if not content:
            raise Invalid("content is required")
        if not svc.conversations.exists(cid):
            raise NotFound(f"conversation {cid} not found")
        if body.get("effort") not in (None, "low", "medium", "xhigh"):
            raise Invalid("effort must be low, medium or xhigh")
        return sse_response(svc.assistant.converse(cid, content, body.get("thinking"), body.get("effort")), request)

    # ------------------------------------------------------------------ stats
    @app.get("/api/stats/summary")
    async def stats_summary(request: Request, days: int = 7):
        svc = svc_of(request)
        return stats_mod.summary(svc.db, svc.runs, days)

    # ------------------------------------------------------------------ frontend (SPA)
    if DIST.exists():
        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            f = (DIST / path).resolve()
            if path and f.is_file() and DIST.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_ui():
            return JSONResponse({"detail": "frontend not built yet: run `pnpm build` in web/ (API is at /api)"})

    return app


app = create_app()

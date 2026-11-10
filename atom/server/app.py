"""FastAPI application: REST + SSE API for the Atom dashboard (see docs/DASHBOARD_API.md)."""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .. import stats as stats_mod
from ..assistant import Assistant
from ..config import LLM_PROFILES, ROOT
from ..events import PING
from ..llm import LLMError
from ..scheduler import describe, normalize_trigger, preview
from ..services import Services
from ..settings_store import SettingsError
from ..stores import Conflict, Invalid, NotFound
from ..uploads import media_type
from ..tools import build_tools
from pydantic import BaseModel, Field


class McpServerIn(BaseModel):
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = {}
    disabled: bool = False

class ConnectorIn(BaseModel):
    type: str
    enabled: bool = True
    config: dict[str, Any] = {}


class ImageLabIn(BaseModel):
    model: str = ""                    # "" / "z-image" = default service, otherwise an SDXL model id
    prompt: str = Field(min_length=1, max_length=4000)
    size: str = "1024x1024"
    seed: int | None = None
    steps: int | None = Field(default=None, ge=1, le=60)
    cfg: float | None = Field(default=None, ge=1, le=15)
    sampler: str | None = None
    negative_prompt: str | None = Field(default=None, max_length=2000)
    image_id: str | None = None        # an uploaded image (POST /api/uploads) to start from: image-to-image
    strength: float | None = Field(default=None, ge=0.05, le=0.95)    # how much to change it (higher = more)


class VariableIn(BaseModel):
    value: str | None = None          # omit to keep the stored value
    secret: bool = False
    description: str = ""
    domains: list[str] = []


VERSION = "0.6.0"
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
        vision = False
        if healthy and hasattr(svc.llm, "vision"):
            try:
                vision = await asyncio.wait_for(svc.llm.vision(), timeout=2.5)
            except Exception:  # noqa: BLE001
                vision = False
        roles = {eff.agent_slot: "agent", eff.extract_slot: "extract", eff.chat_slot: "chat"}
        return {"version": VERSION,
                "llm": {"healthy": healthy, "profile": eff.llm_profile, "base_url": eff.llm_base_url, "model": eff.llm_model, "vision": vision,
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

    # ------------------------------------------------------------------ models
    @app.get("/api/models")
    async def list_models(request: Request):
        svc = svc_of(request)
        return {"active": svc.settings.effective().llm_profile, "models": await svc.models.list()}

    @app.post("/api/models/{profile}/activate")
    async def activate_model(request: Request, profile: str, body: dict = Body(default={})):
        """Make `profile` the default model. Starts its server if it is downloaded but not running."""
        svc = svc_of(request)
        if profile not in LLM_PROFILES:
            raise NotFound(f"unknown model '{profile}'")
        svc.settings.update({"llm_profile": profile})
        if body.get("start", True) and svc.models.installed(profile) and not await svc.models.running(profile):
            svc.models.start(profile)
        svc.bus.publish_global("status", status=await status_payload(svc))
        return {"active": profile, "models": await svc.models.list()}

    @app.post("/api/models/{profile}/{action}")
    async def model_action(request: Request, profile: str, action: str):
        svc = svc_of(request)
        if profile not in LLM_PROFILES:
            raise NotFound(f"unknown model '{profile}'")
        if action == "start":
            if not svc.models.installed(profile):
                raise Conflict(f"{LLM_PROFILES[profile]['label']} is not downloaded yet")
            if not await svc.models.running(profile):
                svc.models.start(profile)
        elif action == "stop":
            if not svc.models.managed(profile) and svc.models.external_pid(profile) is None:
                raise Conflict("no llama-server found on this model's port (it may not be running)")
            svc.models.stop(profile)
        elif action == "download":
            svc.models.download(profile)
        else:
            raise NotFound(f"unknown action '{action}'")
        return {"active": svc.settings.effective().llm_profile, "models": await svc.models.list()}

    @app.get("/api/fs/dirs")
    async def fs_dirs(path: str = Query("")):
        """Subfolders of `path` (default: home) for the working-folder picker. The server is local-only."""
        p = Path(path or "~").expanduser()
        if not p.is_dir():
            raise HTTPException(404, f"'{path}' is not a folder")
        p = p.resolve()
        try:
            names = sorted((c.name for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")), key=str.lower)
        except PermissionError:
            raise HTTPException(403, "no permission to read that folder") from None
        return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "home": str(Path.home()),
                "dirs": names[:500]}

    # ------------------------------------------------------------------ agents
    @app.get("/api/tools")
    async def list_tools(request: Request):
        svc = svc_of(request)
        tools = {**build_tools(), **svc.mcp.tools, **svc.connectors.tools}
        eff = svc.settings.effective()
        from ..files import FILE_TOOLS
        gate = {"terminal": eff.terminal_enabled, "generate_image": eff.imagegen_enabled,
                **{n: eff.terminal_enabled for n in FILE_TOOLS}}
        return [{"name": t.name, "description": t.description, "side_effect": t.side_effect,
                 "enabled": gate.get(t.name, True)}
                for t in tools.values()]

    @app.get("/api/chat/tools")
    async def chat_tools(request: Request):
        """Tools the chat assistant can call in the current session."""
        svc = svc_of(request)
        from ..files import FILE_TOOLS, WRITE_TOOLS
        term = svc.settings.effective().terminal_enabled
        return [{"name": t["function"]["name"], "description": t["function"]["description"],
                 "side_effect": t["function"]["name"].startswith("propose_") or t["function"]["name"] in ("run_agent", "run_command") or t["function"]["name"] in WRITE_TOOLS,
                 "enabled": term or not (t["function"]["name"] == "run_command" or t["function"]["name"] in FILE_TOOLS)}
                for t in svc.assistant.tool_specs(include_disabled=True)]

    def _mcp_payload(svc) -> dict:
        cfgs = svc.mcp.load_config()
        blank = {"state": "pending", "tools": 0, "tool_names": [], "error": None}
        return {"config_path": str(svc.mcp.config_path),
                "servers": [{"name": n, "config": c, **svc.mcp.status.get(n, blank)} for n, c in cfgs.items()]}

    @app.get("/api/mcp")
    async def mcp_status(request: Request):
        return _mcp_payload(svc_of(request))

    @app.post("/api/mcp/reload")
    async def mcp_reload(request: Request):
        svc = svc_of(request)
        await svc.refresh_mcp()
        return _mcp_payload(svc)

    @app.put("/api/mcp/servers/{name}")
    async def mcp_put_server(request: Request, name: str, body: McpServerIn):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            raise HTTPException(422, "Name must be 1-40 letters, digits, '-' or '_'.")
        if bool(body.command) == bool(body.url):
            raise HTTPException(422, "Provide exactly one of `command` (local) or `url` (remote).")
        svc = svc_of(request)
        await svc.mcp.set_server(name, body.model_dump(exclude_none=True, exclude_defaults=True))
        svc.sync_mcp_tools()
        return _mcp_payload(svc)

    @app.delete("/api/mcp/servers/{name}")
    async def mcp_delete_server(request: Request, name: str):
        svc = svc_of(request)
        await svc.mcp.remove_server(name)
        svc.sync_mcp_tools()
        return _mcp_payload(svc)

    # ------------------------------------------------------------------ connectors
    @app.get("/api/connectors")
    async def list_connectors(request: Request):
        return svc_of(request).connectors.payload()

    @app.put("/api/connectors/{name}")
    async def put_connector(request: Request, name: str, body: ConnectorIn):
        svc = svc_of(request)
        svc.connectors.put(name, body.type, body.enabled, body.config)
        svc.sync_mcp_tools()
        return svc.connectors.payload()

    @app.delete("/api/connectors/{name}")
    async def delete_connector(request: Request, name: str):
        svc = svc_of(request)
        svc.connectors.delete(name)
        svc.sync_mcp_tools()
        return svc.connectors.payload()

    @app.post("/api/connectors/{name}/oauth/start")
    async def connector_oauth_start(request: Request, name: str):
        redirect = f"{request.url.scheme}://{request.url.netloc}/api/oauth/callback"
        return {"auth_url": svc_of(request).connectors.oauth_begin(name, redirect), "redirect_uri": redirect}

    @app.post("/api/connectors/{name}/oauth/signout")
    async def connector_oauth_signout(request: Request, name: str):
        svc = svc_of(request)
        svc.connectors.oauth_signout(name)
        svc.sync_mcp_tools()
        return svc.connectors.payload()

    @app.get("/api/oauth/callback")
    async def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
        import html as _html
        svc = svc_of(request)
        try:
            if error or not code:
                raise Invalid(f"Sign-in was cancelled or failed ({error or 'no code returned'}).")
            name = await svc.connectors.oauth_complete(state, code)
            svc.sync_mcp_tools()
            title, msg = "Signed in", f"Connector \u201c{_html.escape(name)}\u201d is connected. You can close this tab."
        except Invalid as e:
            title, msg = "Sign-in failed", _html.escape(str(e))
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{title}</title>"
                            "<body style='font:16px system-ui;max-width:32rem;margin:15vh auto;padding:0 1rem'>"
                            f"<h2>{title}</h2><p>{msg}</p>")

    @app.post("/api/connectors/{name}/test")
    async def test_connector(request: Request, name: str):
        return await svc_of(request).connectors.test(name)

    # ------------------------------------------------------------------ variables
    @app.get("/api/variables")
    async def list_variables(request: Request):
        return svc_of(request).variables.list()

    @app.put("/api/variables/{name}")
    async def put_variable(request: Request, name: str, body: VariableIn):
        return svc_of(request).variables.put(name, value=body.value, secret=body.secret,
                                             description=body.description, domains=body.domains)

    @app.delete("/api/variables/{name}", status_code=204)
    async def delete_variable(request: Request, name: str):
        svc_of(request).variables.delete(name)

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
        images = svc.uploads.validate(body.get("images"))
        if svc.uploads.needs_vision(images) and not await svc.llm.vision():
            raise Invalid("The model server has no vision projector loaded (start llama-server with --mmproj), "
                          "so it cannot read images or scanned PDFs.")
        run = svc.run_manager.enqueue(task, agent, trigger="manual", start_url=body.get("start_url") or None,
                                      overrides=body.get("overrides") or {}, images=images)
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
    def skill_folder(svc, project_id: str | None) -> str | None:
        """Working folder of a project (where project-level skills live), or None for user-level only."""
        return svc.projects.get(project_id)["folder"] if project_id else None

    @app.get("/api/skills")
    async def list_skills(request: Request, project_id: str | None = None):
        svc = svc_of(request)
        return svc.skills.list(skill_folder(svc, project_id))

    @app.post("/api/skills", status_code=201)
    async def create_skill(request: Request, body: dict = Body(...), project_id: str | None = None):
        svc = svc_of(request)
        return svc.skills.create({**body, "created_by": "user"}, skill_folder(svc, project_id))

    @app.get("/api/skills/{name}")
    async def get_skill(request: Request, name: str, project_id: str | None = None):
        svc = svc_of(request)
        return svc.skills.get(name, skill_folder(svc, project_id))

    @app.put("/api/skills/{name}")
    async def update_skill(request: Request, name: str, body: dict = Body(...), project_id: str | None = None):
        svc = svc_of(request)
        return svc.skills.update(name, body, skill_folder(svc, project_id))

    @app.delete("/api/skills/{name}", status_code=204)
    async def delete_skill(request: Request, name: str, project_id: str | None = None):
        svc = svc_of(request)
        svc.skills.delete(name, skill_folder(svc, project_id))

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

    # ------------------------------------------------------------------ image uploads
    @app.post("/api/uploads", status_code=201)
    async def upload_file(request: Request):
        """Upload an image or document (PNG/JPEG/GIF/WebP, PDF, Markdown, text) -> {id, mime, size, name, kind, url, ...}.
        Either JSON `{"data_url": "data:<type>;base64,...", "name": "x"}` or the raw file as the request body with
        `?name=report.pdf` (cheaper for big files). The type is sniffed from the bytes, never taken from the client."""
        uploads = svc_of(request).uploads
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
            except ValueError as e:
                raise Invalid("invalid JSON body") from e
            if not isinstance(body, dict):
                raise Invalid("expected a JSON object")
            data_url, name = body.get("data_url") or "", str(body.get("name") or "")
            info = await asyncio.to_thread(uploads.save_data_url, data_url, name)
        else:
            info = await asyncio.to_thread(uploads.save, await request.body(), request.query_params.get("name", ""))
        return {**info, "url": f"/api/uploads/{info['id']}"}

    @app.get("/api/uploads/{uid}/info")
    async def upload_info(request: Request, uid: str):
        info = svc_of(request).uploads.info(uid)
        return {**info, "url": f"/api/uploads/{uid}"}

    @app.get("/api/uploads/{uid}")
    async def get_upload(request: Request, uid: str):
        path = svc_of(request).uploads.path(uid)
        return FileResponse(path, media_type=media_type(path),
                            headers={"Cache-Control": "public, max-age=31536000, immutable",
                                     "X-Content-Type-Options": "nosniff"})

    # ------------------------------------------------------------------ local file preview
    PREVIEW_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                     ".webp": "image/webp", ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
                     ".md": "text/plain; charset=utf-8", ".json": "text/plain; charset=utf-8",
                     ".csv": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8"}

    @app.get("/api/local-file")
    async def local_file(request: Request, path: str = Query(...)):
        """Serve a file named in chat for preview. Only previewable types, and only inside a project folder or data/."""
        svc = svc_of(request)
        try:
            p = Path(path).expanduser().resolve()           # resolve() follows symlinks, so links cannot escape
        except (OSError, RuntimeError):
            raise NotFound("file not found") from None
        eff = svc.settings.effective()
        roots = [eff.data_dir.resolve(), Path(eff.imagelab_output_dir).expanduser().resolve()]
        roots += [Path(pr["folder"]).resolve() for pr in svc.projects.list() if pr["folder"]]
        ctype = PREVIEW_TYPES.get(p.suffix.lower())
        if not p.is_absolute() or ctype is None or not p.is_file() or not any(p.is_relative_to(r) for r in roots):
            raise NotFound("file not found, or not previewable")
        return FileResponse(p, media_type=ctype, content_disposition_type="inline",
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ images page (no chat model)
    @app.get("/api/imagelab/models")
    async def imagelab_models(request: Request):
        from .. import imagelab
        return await imagelab.models(svc_of(request).settings.effective())

    @app.post("/api/imagelab/generate")
    async def imagelab_generate(request: Request, body: ImageLabIn):
        from .. import imagegen, imagelab
        svc = svc_of(request)
        args = body.model_dump()
        image = None
        if args.pop("image_id"):
            uid = body.image_id
            if svc.uploads.info(uid)["kind"] != "image":              # NotFound for an unknown id
                raise Invalid("the attached upload is not an image")
            image = await asyncio.to_thread(svc.uploads.path(uid).read_bytes)
        try:
            return await imagelab.generate(svc.settings.effective(), image=image, **args)
        except imagegen.ImageGenError as e:
            raise HTTPException(502, str(e)) from e

    # ------------------------------------------------------------------ chat
    @app.get("/api/conversations")
    async def list_conversations(request: Request):
        return svc_of(request).conversations.list()

    @app.post("/api/conversations", status_code=201)
    async def create_conversation(request: Request, body: dict = Body(default={})):
        return svc_of(request).conversations.create(body.get("title"), body.get("project_id"))

    # ------------------------------------------------------------------ projects
    @app.get("/api/projects")
    async def list_projects(request: Request):
        return svc_of(request).projects.list()

    @app.post("/api/projects", status_code=201)
    async def create_project(request: Request, body: dict = Body(...)):
        return svc_of(request).projects.create(body.get("name"), body.get("folder"))

    @app.put("/api/projects/{pid}")
    async def update_project(request: Request, pid: str, body: dict = Body(...)):
        return svc_of(request).projects.update(pid, body.get("name"), body.get("folder"))

    @app.delete("/api/projects/{pid}", status_code=204)
    async def delete_project(request: Request, pid: str):
        svc_of(request).projects.delete(pid)

    @app.get("/api/conversations/{cid}")
    async def get_conversation(request: Request, cid: str):
        return svc_of(request).conversations.get(cid)

    @app.get("/api/conversations/{cid}/context")
    async def conversation_context(request: Request, cid: str, effort: str | None = None, thinking: bool | None = None):
        svc = svc_of(request)
        proj = svc.conversations.project_of(cid)
        return await svc.assistant.context_usage(cid, effort, thinking, workdir=(proj or {}).get("folder"))

    @app.post("/api/conversations/{cid}/compact")
    async def compact_conversation(request: Request, cid: str, body: dict = Body(default={})):
        """Manual 'compact now': prune old tool output and fold older messages into the rolling summary."""
        svc = svc_of(request)
        if not svc.conversations.exists(cid):
            raise NotFound(f"conversation {cid} not found")
        proj = svc.conversations.project_of(cid)
        return await svc.assistant.compact(cid, body.get("thinking"), body.get("effort"), workdir=(proj or {}).get("folder"))

    @app.put("/api/conversations/{cid}")
    async def rename_conversation(request: Request, cid: str, body: dict = Body(...)):
        svc = svc_of(request)
        if "project_id" in body:
            svc.conversations.move(cid, body.get("project_id"))
        if body.get("title") is not None or "project_id" not in body:
            svc.conversations.rename(cid, body.get("title") or "Chat")
        return {"id": cid, "title": body.get("title"), "project_id": body.get("project_id")}

    @app.delete("/api/conversations/{cid}", status_code=204)
    async def delete_conversation(request: Request, cid: str):
        svc_of(request).conversations.delete(cid)

    @app.post("/api/conversations/{cid}/messages")
    async def post_message(request: Request, cid: str, body: dict = Body(...)):
        svc = svc_of(request)
        content = (body.get("content") or "").strip()
        images = svc.uploads.validate(body.get("images"))
        if not content and not images:
            raise Invalid("content is required")
        if svc.uploads.needs_vision(images) and not await svc.llm.vision():
            raise Invalid("The model server has no vision projector loaded (start llama-server with --mmproj), "
                          "so it cannot read images or scanned PDFs.")
        if not svc.conversations.exists(cid):
            raise NotFound(f"conversation {cid} not found")
        if body.get("effort") not in (None, "low", "medium", "xhigh"):
            raise Invalid("effort must be low, medium or xhigh")
        proj = svc.conversations.project_of(cid)
        workdir = (proj or {}).get("folder") or (body.get("workdir") or "").strip() or None   # a project's folder wins
        if body.get("mode") not in (None, "auto", "manual", "plan"):
            raise Invalid("mode must be auto, manual or plan")
        return sse_response(svc.assistant.converse(cid, content, body.get("thinking"), body.get("effort"), images,
                                                  workdir=workdir, mode=body.get("mode"), can_approve=True), request)

    @app.post("/api/chat/approvals/{call_id}")
    async def decide_approval(request: Request, call_id: str, body: dict = Body(...)):
        if not svc_of(request).assistant.decide(call_id, bool(body.get("approve"))):
            raise NotFound("no pending approval with that id (it may have timed out)")
        return {"ok": True}

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
                # Vite file names carry a content hash, so assets can be cached for good.
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                return FileResponse(f, headers={"Cache-Control": cache})
            # index.html names the current bundle: always revalidate, or a browser keeps running an old UI.
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        async def no_ui():
            return JSONResponse({"detail": "frontend not built yet: run `pnpm build` in web/ (API is at /api)"})

    return app


app = create_app()

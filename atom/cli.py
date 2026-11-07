"""CLI: python -m atom <command>"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import get_settings
from .services import Services


def console_printer(ev: dict) -> None:
    t = ev.get("type")
    if t == "llm_end":
        print(f"[{ev['step']}] llm {ev['llm_seconds']}s prompt={ev['prompt_tokens']} (new {ev['processed_tokens']}, "
              f"cached {ev['cached_tokens']}) out={ev['completion_tokens']} {ev['decode_tps']} tok/s"
              f"{' [thinking]' if ev.get('think') else ''}")
    elif t == "tool_end":
        first = (ev.get("result") or "").splitlines()[0][:110] if ev.get("result") else ""
        print(f"    {ev['name']} -> {'ok' if ev['ok'] else 'ERR'}  {first}")
    elif t == "tool_start":
        print(f"    {ev['name']} {json.dumps(ev['arguments'], ensure_ascii=False)[:100]}")
    elif t == "compact":
        print(f"    [compacted history, {ev['summarized_actions']} actions]")


async def cmd_run(a: argparse.Namespace) -> int:
    s = get_settings()
    if a.headed:
        s.headless = False
    svc = Services(s)
    if not await svc.llm.healthy():
        print(f"LLM server not reachable at {s.llm_base_url}. Start it with: ops/llama-server.sh", file=sys.stderr)
        return 2
    await svc.startup(scheduler=False)
    agent = svc.agents.find(a.agent) if a.agent else svc.agents.default()
    if not agent:
        print(f"agent '{a.agent}' not found", file=sys.stderr)
        return 2
    overrides = {"max_steps": a.max_steps} if a.max_steps else {}
    if a.thinking:
        overrides["thinking"] = a.thinking
    res = await svc.run_manager.run_inline(
        a.task, agent, start_url=a.url, overrides=overrides, trigger="api",
        console=None if a.quiet else console_printer, allowed_domains=a.allow or None,
        allow_private=True if a.allow_private else None)
    await svc.shutdown()
    print("\n=== RESULT ===")
    print(json.dumps({"status": res.status, "success": res.success, "result": res.result, "error": res.error,
                      "steps": res.steps, "wall_s": round(res.wall_seconds, 1), "prompt_tokens": res.prompt_tokens,
                      "cached_tokens": res.cached_tokens, "completion_tokens": res.completion_tokens,
                      "run_id": res.run_id, "trace": str(res.run_dir / "trace.zip")}, indent=2, ensure_ascii=False,
                     default=str))
    return 0 if res.success else 1


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn
    s = get_settings()
    uvicorn.run("atom.server.app:app", host=a.host or s.server_host, port=a.port or s.server_port,
                log_level="info", timeout_graceful_shutdown=5)
    return 0


def cmd_runs(a: argparse.Namespace) -> int:
    svc = Services(get_settings())
    items, total = svc.runs.list(limit=a.limit)
    for r in items:
        print(" | ".join(str(x) for x in (r["id"], r["status"], r["steps"], r["wall_seconds"], r["task"][:70])))
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    svc = Services(get_settings())
    for st in svc.runs.steps(a.run_id):
        print(st["idx"], st["kind"], st["name"], st["ok"], (st["result"] or "")[:140].replace("\n", " | "))
    return 0


async def cmd_llm_check(a: argparse.Namespace) -> int:
    svc = Services(get_settings())
    ok = await svc.llm.healthy()
    print("healthy:", ok)
    if ok:
        r = await svc.llm.chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=8)
        print("reply:", r.content.strip(), f"({r.seconds:.1f}s)", "slots:", await svc.llm.slots())
    await svc.llm.aclose()
    return 0 if ok else 2


def main() -> None:
    p = argparse.ArgumentParser(prog="atom")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a single agent task")
    r.add_argument("task")
    r.add_argument("--url")
    r.add_argument("--agent", help="agent name or id (default: the default agent)")
    r.add_argument("--allow", action="append", help="allowed domain (repeatable); default: the agent's list")
    r.add_argument("--allow-private", action="store_true", help="allow localhost/LAN targets")
    r.add_argument("--max-steps", type=int)
    r.add_argument("--thinking", choices=["off", "auto", "on"])
    r.add_argument("--headed", action="store_true")
    r.add_argument("--quiet", action="store_true")
    sv = sub.add_parser("serve", help="start the dashboard backend")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    sub.add_parser("llm-check")
    ls = sub.add_parser("runs")
    ls.add_argument("--limit", type=int, default=15)
    sh = sub.add_parser("show")
    sh.add_argument("run_id")
    a = p.parse_args()
    if a.cmd == "run":
        sys.exit(asyncio.run(cmd_run(a)))
    if a.cmd == "serve":
        sys.exit(cmd_serve(a))
    if a.cmd == "llm-check":
        sys.exit(asyncio.run(cmd_llm_check(a)))
    if a.cmd == "runs":
        sys.exit(cmd_runs(a))
    if a.cmd == "show":
        sys.exit(cmd_show(a))


if __name__ == "__main__":
    main()

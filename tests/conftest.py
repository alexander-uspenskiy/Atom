"""Test fixtures: a scripted fake LLM, an isolated Services instance, a TestClient, and the fixture web site."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atom.config import Settings
from atom.llm import LLM, LLMResult
from atom.server.app import create_app
from atom.services import Services
from evals.fixtures.server import FixtureServer


class FakeLLM:
    """Replays scripted responses. Each script item is a dict:
    {content, reasoning, calls: [(tool, args)], prompt, cached, out, delay}"""

    def __init__(self, script: list[dict] | None = None):
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []
        self.default = {"calls": [("done", {"evidence": "-", "result": "ok", "success": True})]}

    def push(self, *items: dict) -> None:
        self.script.extend(items)

    async def healthy(self) -> bool:
        return True

    async def slots(self) -> list[dict]:
        return [{"id": i, "busy": False, "n_ctx": 32768} for i in range(3)]

    def reconfigure(self, settings) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def chat(self, messages, *, tools=None, think=False, effort="low", slot=None, json_schema=None,
                   max_tokens=1024, temperature=None, on_delta=None) -> LLMResult:
        self.calls.append({"messages": json.loads(json.dumps(messages)), "tools": [t["function"]["name"] for t in tools or []],
                           "think": think, "effort": effort, "slot": slot, "json_schema": json_schema})
        item = self.script.pop(0) if self.script else self.default
        if item.get("delay"):
            await asyncio.sleep(item["delay"])
        content, reasoning = item.get("content", ""), item.get("reasoning", "")
        for ch, text in (("reasoning", reasoning), ("content", content)):
            for i in range(0, len(text), 8):
                if on_delta:
                    r = on_delta(ch, text[i:i + 8])
                    if asyncio.iscoroutine(r):
                        await r
        raw = {i: {"id": f"call_{len(self.calls)}_{i}", "name": n, "arguments": json.dumps(a)}
               for i, (n, a) in enumerate(item.get("calls", []))}
        prompt, cached, out = item.get("prompt", 1000), item.get("cached", 800), item.get("out", 20)
        timings = {"cache_n": cached, "prompt_n": prompt - cached, "prompt_ms": 500.0, "predicted_n": out,
                   "predicted_ms": 1000.0 * out / 10, "prompt_per_second": (prompt - cached) / 0.5,
                   "predicted_per_second": 10.0}
        return LLM._build([content], [reasoning] if reasoning else [], raw,
                          {"prompt_tokens": prompt, "completion_tokens": out}, timings, "stop", 1.0)


@pytest.fixture(scope="session")
def site():
    srv = FixtureServer().start()
    yield srv
    srv.stop()


@pytest.fixture
def fake() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def svc(tmp_path, fake):
    base = Settings(data_dir=tmp_path, headless=True, max_wall_s=120, llm_base_url="http://fake/v1")
    return Services(base, llm=fake, db_path=str(tmp_path / "atom.db"))


@pytest.fixture
def client(svc):
    with TestClient(create_app(svc, start_scheduler=True)) as c:
        yield c


def wait_run(client: TestClient, run_id: str, timeout: float = 90) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/runs/{run_id}").json()["run"]
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish: {r}")


def read_sse(client: TestClient, method: str, url: str, json_body: dict | None = None) -> list[dict]:
    events = []
    with client.stream(method, url, json=json_body) as resp:
        assert resp.status_code == 200, resp.read()
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events


def make_local_agent(client: TestClient, **kw) -> dict:
    body = {"name": "Local test agent", "allow_private": True, "memory_scope": "global", **kw}
    r = client.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()

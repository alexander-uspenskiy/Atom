"""Async streaming client for an OpenAI-compatible llama-server.

Uses httpx directly (not the openai SDK) so we can read llama-server's `timings` block (cache hits, prefill and
decode milliseconds) and stream content / reasoning deltas to the dashboard while the model is still talking.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    parse_error: str | None = None


@dataclass
class LLMResult:
    content: str
    reasoning: str
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any]       # ready to append to history (no reasoning text)
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int                      # prompt tokens served from the slot cache
    processed_tokens: int                   # prompt tokens actually evaluated this call
    seconds: float
    prefill_ms: float = 0.0
    decode_ms: float = 0.0
    prefill_tps: float = 0.0
    decode_tps: float = 0.0
    finish_reason: str = ""
    timings: dict[str, Any] = field(default_factory=dict)


DeltaCb = Callable[[str, str], Awaitable[None] | None]   # (channel, text)


class LLM:
    def __init__(self, settings: Settings):
        self.s = settings
        self._client = self._make_client(settings)

    @staticmethod
    def _make_client(s: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=s.llm_base_url, timeout=httpx.Timeout(900, connect=5),
                                 headers={"Authorization": f"Bearer {s.llm_api_key}"})

    def reconfigure(self, settings: Settings) -> None:
        """Called when settings change. Sampling params are read per call; only the URL needs a new client."""
        old, self.s = self.s, settings
        if old.llm_base_url != settings.llm_base_url or old.llm_api_key != settings.llm_api_key:
            stale = self._client
            self._client = self._make_client(settings)
            asyncio.ensure_future(stale.aclose())

    async def aclose(self) -> None:
        await self._client.aclose()

    def _root(self) -> str:
        return self.s.llm_base_url.removesuffix("/").removesuffix("/v1")

    async def healthy(self) -> bool:
        try:
            r = await self._client.get(self._root() + "/health", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def slots(self) -> list[dict]:
        """Live slot info from llama-server (/slots). Empty if unavailable."""
        try:
            r = await self._client.get(self._root() + "/slots", timeout=3)
            data = r.json() if r.status_code == 200 else []
            return [{"id": d.get("id"), "busy": bool(d.get("is_processing")), "n_ctx": d.get("n_ctx")} for d in data]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------
    async def chat(self, messages: list[dict], *, tools: list[dict] | None = None, think: bool = False,
                   effort: str = "low", slot: int | None = None, json_schema: dict | None = None,
                   max_tokens: int = 1024, temperature: float | None = None,
                   on_delta: DeltaCb | None = None) -> LLMResult:
        s = self.s
        body: dict[str, Any] = {
            "model": s.llm_model, "messages": messages, "max_tokens": max_tokens,
            "temperature": s.temperature if temperature is None else temperature,
            "top_p": s.top_p, "top_k": s.top_k, "presence_penalty": s.presence_penalty,
            "cache_prompt": True, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": think, **({"reasoning_effort": effort} if think else {})},
        }
        if think:  # official thinking-mode sampling
            body.update(temperature=1.0 if temperature is None else temperature, top_p=0.95, presence_penalty=0.0)
        if slot is not None:
            body["id_slot"] = slot
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "result", "schema": json_schema, "strict": True}}
        last_exc: Exception | None = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                return await self._stream_once(body, t0, on_delta)
            except _Retryable as e:
                last_exc = e
                await asyncio.sleep(2 * (attempt + 1))
            except httpx.TransportError as e:
                # only retry if nothing was streamed yet (handled in _stream_once by raising _Retryable)
                raise LLMError(f"LLM connection failed: {e}") from e
        raise LLMError(f"LLM call failed: {last_exc}")

    async def _stream_once(self, body: dict, t0: float, on_delta: DeltaCb | None) -> LLMResult:
        content: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}
        finish = ""
        started = False
        # One dedicated connection per generation, closed explicitly on exit. A pooled connection that was
        # cancelled mid-stream can linger, and then llama-server keeps generating tokens nobody will read.
        client = self._make_client(self.s)
        try:
            async with client.stream("POST", "/chat/completions", json=body) as r:
                if r.status_code >= 500 or r.status_code == 429:
                    raise _Retryable(f"server {r.status_code}: {(await r.aread())[:300]!r}")
                if r.status_code >= 400:
                    raise LLMError(f"request rejected {r.status_code}: {(await r.aread())[:500]!r}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    started = True
                    d = json.loads(payload)
                    if d.get("usage"):
                        usage = d["usage"]
                    if d.get("timings"):
                        timings = d["timings"]
                    for ch in d.get("choices", []):
                        if ch.get("finish_reason"):
                            finish = ch["finish_reason"]
                        delta = ch.get("delta") or {}
                        if delta.get("reasoning_content"):
                            reasoning.append(delta["reasoning_content"])
                            await _emit(on_delta, "reasoning", delta["reasoning_content"])
                        if delta.get("content"):
                            content.append(delta["content"])
                            await _emit(on_delta, "content", delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
        except httpx.TransportError as e:
            if not started:
                raise _Retryable(f"connection error: {e}") from e
            raise LLMError(f"stream interrupted: {e}") from e
        finally:
            await asyncio.shield(client.aclose())
        return self._build(content, reasoning, calls, usage, timings, finish, time.perf_counter() - t0)

    @staticmethod
    def _build(content: list[str], reasoning: list[str], raw_calls: dict[int, dict[str, str]], usage: dict,
               timings: dict, finish: str, seconds: float) -> LLMResult:
        calls: list[ToolCall] = []
        for idx in sorted(raw_calls):
            rc = raw_calls[idx]
            raw = rc["arguments"]
            args, err = {}, None
            try:
                args = json.loads(raw) if raw.strip() else {}
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except ValueError as e:
                err = f"invalid JSON arguments: {e}"
            calls.append(ToolCall(rc["id"] or f"call_{idx}", rc["name"], args, raw, err))
        text = "".join(content)
        assistant: dict[str, Any] = {"role": "assistant", "content": text}
        if calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)}}
                for c in calls]
        prompt_n = int(timings.get("prompt_n", usage.get("prompt_tokens", 0)))
        cache_n = int(timings.get("cache_n", 0))
        prefill_ms = float(timings.get("prompt_ms", 0.0))
        decode_ms = float(timings.get("predicted_ms", 0.0))
        completion = int(usage.get("completion_tokens", timings.get("predicted_n", 0)))
        return LLMResult(
            content=text, reasoning="".join(reasoning), tool_calls=calls, assistant_message=assistant,
            prompt_tokens=int(usage.get("prompt_tokens", prompt_n + cache_n)), completion_tokens=completion,
            cached_tokens=cache_n, processed_tokens=prompt_n, seconds=seconds,
            prefill_ms=prefill_ms, decode_ms=decode_ms,
            prefill_tps=float(timings.get("prompt_per_second", (prompt_n / (prefill_ms / 1000)) if prefill_ms else 0)),
            decode_tps=float(timings.get("predicted_per_second", (completion / (decode_ms / 1000)) if decode_ms else 0)),
            finish_reason=finish, timings=timings)


class _Retryable(Exception):
    pass


async def _emit(cb: DeltaCb | None, channel: str, text: str) -> None:
    if cb is None:
        return
    r = cb(channel, text)
    if inspect.isawaitable(r):
        await r

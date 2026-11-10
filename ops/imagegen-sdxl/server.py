"""Local SDXL image service for Atom: Juggernaut XL, RealVisXL, Pony Diffusion and Illustrious XL via diffusers on MPS.

Runs in its own environment (ops/imagegen-sdxl/.venv) so torch/diffusers stay out of Atom's dependencies.
Same wire contract as ops/imagegen (Z-Image), plus a `model` field (the OpenAI field) that picks the checkpoint.
Checkpoints load on demand: one at a time, a different `model` unloads the current one first, and the loaded one is
freed after IMAGEGEN_SDXL_IDLE_S seconds without use. One image at a time; callers queue.

    cd ops/imagegen-sdxl && uv run python server.py          # http://127.0.0.1:8091

POST /v1/images/generations   {"prompt": "...", "model": "illustrious", "size": "1024x1024", "seed": 1,
                               "steps": 28, "cfg": 5.5, "sampler": "euler_a", "negative_prompt": "..."}
    -> {"data": [{"path": "<abs png>", "preview_path": "<abs jpg>", "model": "illustrious", "seed": 1,
                  "width": 1024, "height": 1024, "seconds": 41.2}]}
GET  /v1/models               -> registry with style (natural|tags) and whether the checkpoint file is present
GET  /health                  -> {"ok": true, "loaded": "<model>|null", ...}

No safety checker or content filter is applied. Model names, files and per-model defaults live in models.json.
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MODELS_DIR = Path(os.environ.get("IMAGEGEN_SDXL_DIR", str(ROOT / "data" / "models" / "sdxl")))
REGISTRY_FILE = Path(os.environ.get("IMAGEGEN_SDXL_REGISTRY", str(HERE / "models.json")))
OUT_DIR = Path(os.environ.get("IMAGEGEN_SDXL_OUT", str(ROOT / "data" / "images")))
IDLE_S = int(os.environ.get("IMAGEGEN_SDXL_IDLE_S", "300"))
HOST = os.environ.get("IMAGEGEN_SDXL_HOST", "127.0.0.1")
PORT = int(os.environ.get("IMAGEGEN_SDXL_PORT", "8091"))
MIN_SIDE, MAX_SIDE, MAX_PIXELS = 512, 1536, 1_700_000
PREVIEW_SIDE = 768
SAMPLERS = ("euler_a", "dpmpp_2m_karras")
CLIP_CHUNK = 75        # CLIP reads 77 tokens including start/end; longer prompts are encoded in chunks

app = FastAPI(title="atom-imagegen-sdxl")
_pipe: Any = None
_loaded_name: str | None = None
_last_used = 0.0
_lock = asyncio.Lock()


# --------------------------------------------------------------------------- registry and prompt helpers (pure)
def load_registry(path: Path = REGISTRY_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    models = data.get("models") or {}
    if not models:
        raise RuntimeError(f"{path} defines no models")
    default = data.get("default") if data.get("default") in models else next(iter(models))
    return {"default": default, "models": models}


def resolve_model(registry: dict, name: str | None) -> tuple[str, dict]:
    key = (name or "").strip().lower() or registry["default"]
    if key in ("default", "sdxl"):
        key = registry["default"]
    cfg = registry["models"].get(key)
    if cfg is None:
        raise HTTPException(404, f"unknown model '{name}'; available: {', '.join(registry['models'])}")
    return key, cfg


def parse_size(size: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{3,4})\s*[x×]\s*(\d{3,4})\s*", size or "")
    if not m:
        raise HTTPException(422, "size must look like 1024x1024")
    w, h = (int(m[1]) // 8 * 8, int(m[2]) // 8 * 8)      # SDXL latents are 1/8 of the image
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE) or w * h > MAX_PIXELS:
        raise HTTPException(422, f"size out of range: each side {MIN_SIDE}-{MAX_SIDE}, at most {MAX_PIXELS} pixels")
    return w, h


def _tags(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


def apply_prefix(prompt: str, prefix: str) -> str:
    """Prepend the model's quality/score tags, skipping any the caller already wrote."""
    have = {t.lower() for t in _tags(prompt)}
    missing = [t for t in _tags(prefix) if t.lower() not in have]
    return ", ".join(missing + [prompt.strip()]) if missing else prompt.strip()


def merge_negative(default: str, extra: str | None) -> str:
    have = {t.lower() for t in _tags(default)}
    return ", ".join(_tags(default) + [t for t in _tags(extra or "") if t.lower() not in have])


def pack_chunks(text: str, count: Callable[[str], int], limit: int = CLIP_CHUNK) -> list[str]:
    """Split a comma-separated prompt into chunks of at most `limit` tokens, breaking only between tags.
    A single tag longer than the limit gets a chunk of its own (the tokenizer truncates it)."""
    chunks: list[str] = []
    cur: list[str] = []
    used = 0
    for tag in _tags(text):
        n = count(tag) + 1                         # +1 for the comma that joins it
        if cur and used + n > limit:
            chunks.append(", ".join(cur))
            cur, used = [], 0
        cur.append(tag)
        used += n
    if cur:
        chunks.append(", ".join(cur))
    return chunks or [""]


# --------------------------------------------------------------------------- model handling (torch is imported lazily)
def _device() -> str:
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load(name: str, cfg: dict):
    path = MODELS_DIR / cfg["file"]
    if not path.is_file():
        raise RuntimeError(f"checkpoint for '{name}' not found: put {cfg['file']} in {MODELS_DIR}")
    import torch
    from diffusers import StableDiffusionXLPipeline
    dev = _device()
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(path), torch_dtype=torch.float16 if dev != "cpu" else torch.float32,
        use_safetensors=True, add_watermarker=False)
    pipe.to(dev)
    pipe.set_progress_bar_config(disable=True)
    return pipe


def _unload() -> None:
    global _pipe, _loaded_name
    _pipe, _loaded_name = None, None
    gc.collect()
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def _set_sampler(pipe, sampler: str) -> None:
    from diffusers import DPMSolverMultistepScheduler, EulerAncestralDiscreteScheduler
    conf = pipe.scheduler.config
    if sampler == "euler_a":
        pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(conf)
    else:                                          # dpmpp_2m_karras
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            conf, use_karras_sigmas=True, algorithm_type="dpmsolver++")


def _encode(pipe, text: str):
    """Encode a prompt of any length: chunk it between tags, encode each chunk, concatenate along the sequence."""
    import torch
    count = lambda s: len(pipe.tokenizer(s, add_special_tokens=False).input_ids)    # noqa: E731
    embeds, pooled = [], None
    for chunk in pack_chunks(text, count):
        pe, _, pp, _ = pipe.encode_prompt(prompt=chunk, prompt_2=chunk, device=pipe.device, num_images_per_prompt=1,
                                          do_classifier_free_guidance=False)
        embeds.append(pe)
        pooled = pp if pooled is None else pooled          # pooled output comes from the first chunk
    return embeds, pooled, torch


def _generate(name: str, cfg: dict, prompt: str, negative: str, w: int, h: int, seed: int, steps: int,
              guidance: float, sampler: str | None = None) -> tuple[Path, float]:
    global _pipe, _loaded_name
    t0 = time.monotonic()
    if _loaded_name != name:
        _unload()                                  # one checkpoint resident at a time
        _pipe, _loaded_name = _load(name, cfg), name
    _set_sampler(_pipe, sampler or cfg.get("sampler", "dpmpp_2m_karras"))
    pos, pos_pooled, torch = _encode(_pipe, prompt)
    neg, neg_pooled, _ = _encode(_pipe, negative)
    n = max(len(pos), len(neg))                    # both sides must have the same sequence length
    empty, _, _ = _encode(_pipe, "")
    pos += empty * (n - len(pos))
    neg += empty * (n - len(neg))
    img = _pipe(prompt_embeds=torch.cat(pos, dim=1), pooled_prompt_embeds=pos_pooled,
                negative_prompt_embeds=torch.cat(neg, dim=1), negative_pooled_prompt_embeds=neg_pooled,
                width=w, height=h, num_inference_steps=steps, guidance_scale=guidance,
                generator=torch.Generator(device="cpu").manual_seed(seed)).images[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.png"
    img.save(path)
    pil = img.convert("RGB")
    pil.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    pil.save(path.with_suffix(".preview.jpg"), "JPEG", quality=85)
    gc.collect()
    return path, time.monotonic() - t0


# --------------------------------------------------------------------------- API
class GenRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    size: str = "1024x1024"
    seed: int | None = None
    steps: int | None = Field(default=None, ge=1, le=60)
    cfg: float | None = Field(default=None, ge=1, le=15)
    sampler: Literal["euler_a", "dpmpp_2m_karras"] | None = None
    negative_prompt: str | None = Field(default=None, max_length=2000)
    n: int = Field(default=1, ge=1, le=1)      # accepted for OpenAI compatibility; one image per call


@app.post("/v1/images/generations")
async def generations(req: GenRequest) -> dict:
    global _last_used
    registry = load_registry()
    name, cfg = resolve_model(registry, req.model)
    w, h = parse_size(req.size)
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    prompt = apply_prefix(req.prompt, cfg.get("prefix", ""))
    negative = merge_negative(cfg.get("negative", ""), req.negative_prompt)
    steps = req.steps or int(cfg.get("steps", 28))
    guidance = req.cfg or float(cfg.get("cfg", 5.5))
    async with _lock:                                   # one image at a time; callers queue
        try:
            path, secs = await asyncio.to_thread(_generate, name, cfg, prompt, negative, w, h, seed, steps, guidance,
                                                 req.sampler)
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        _last_used = time.monotonic()
    return {"created": int(time.time()),
            "data": [{"path": str(path), "preview_path": str(path.with_suffix(".preview.jpg")), "model": name,
                      "seed": seed, "width": w, "height": h, "seconds": round(secs, 1)}]}


@app.get("/v1/models")
async def models() -> dict:
    registry = load_registry()
    return {"default": registry["default"], "samplers": list(SAMPLERS), "data": [
        {"id": k, "style": v.get("style", "natural"), "about": v.get("about", ""),
         "present": (MODELS_DIR / v["file"]).is_file(), "loaded": k == _loaded_name,
         "defaults": {"steps": int(v.get("steps", 28)), "cfg": float(v.get("cfg", 5.5)),
                      "sampler": v.get("sampler", "dpmpp_2m_karras"), "prefix": v.get("prefix", ""),
                      "negative": v.get("negative", "")}}
        for k, v in registry["models"].items()]}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "loaded": _loaded_name, "models_dir": str(MODELS_DIR), "idle_unload_s": IDLE_S}


async def _reaper() -> None:
    while True:
        await asyncio.sleep(15)
        if _pipe is not None and not _lock.locked() and time.monotonic() - _last_used > IDLE_S:
            async with _lock:
                if _pipe is not None and time.monotonic() - _last_used > IDLE_S:
                    await asyncio.to_thread(_unload)


@app.on_event("startup")
async def _startup() -> None:
    global _last_used
    _last_used = time.monotonic()
    asyncio.create_task(_reaper())


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

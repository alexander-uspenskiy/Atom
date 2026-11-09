"""Local image generation service for Atom: Z-Image-Turbo (4-bit) on MLX via mflux.

Runs in its own environment (ops/imagegen/.venv) so mflux/MLX stay out of Atom's dependencies.
Loads the model on the first request and unloads it after IMAGEGEN_IDLE_S seconds without use, so the
~6-8 GB it needs is only resident while images are being made. One image at a time.

    cd ops/imagegen && uv run python server.py          # http://127.0.0.1:8090

POST /v1/images/generations   {"prompt": "...", "size": "1024x1024", "seed": 1, "steps": 9}
    -> {"data": [{"path": "<abs png>", "seed": 1, "width": 1024, "height": 1024, "seconds": 12.3}]}
GET  /health                  -> {"ok": true, "loaded": bool, ...}
"""
from __future__ import annotations

import asyncio
import gc
import os
import random
import re
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MODEL_PATH = os.environ.get("IMAGEGEN_MODEL", str(ROOT / "data" / "models" / "z-image-turbo-4bit"))
OUT_DIR = Path(os.environ.get("IMAGEGEN_OUT", str(ROOT / "data" / "images")))
IDLE_S = int(os.environ.get("IMAGEGEN_IDLE_S", "300"))
HOST = os.environ.get("IMAGEGEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("IMAGEGEN_PORT", "8090"))
MIN_SIDE, MAX_SIDE, MAX_PIXELS = 256, 1536, 1536 * 1024
PREVIEW_SIDE = 768
DEFAULT_STEPS = 9     # Z-Image-Turbo is distilled for 8-9 steps; more does not help

app = FastAPI(title="atom-imagegen")
_model = None
_loaded_at = 0.0
_last_used = 0.0
_lock = asyncio.Lock()


class GenRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    size: str = "1024x1024"
    seed: int | None = None
    steps: int | None = Field(default=None, ge=1, le=20)
    n: int = Field(default=1, ge=1, le=1)      # accepted for OpenAI compatibility; one image per call


def parse_size(size: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{2,4})\s*[x×]\s*(\d{2,4})\s*", size or "")
    if not m:
        raise HTTPException(422, "size must look like 1024x1024")
    w, h = (int(m[1]) // 16 * 16, int(m[2]) // 16 * 16)     # the model works on multiples of 16
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE) or w * h > MAX_PIXELS:
        raise HTTPException(422, f"size out of range: each side {MIN_SIDE}-{MAX_SIDE}, at most {MAX_PIXELS} pixels")
    return w, h


def _load():
    from mflux.models.common.config import ModelConfig
    from mflux.models.z_image import ZImage
    if not Path(MODEL_PATH).exists():
        raise RuntimeError(f"model folder not found: {MODEL_PATH}")
    return ZImage(model_config=ModelConfig.z_image_turbo(), model_path=MODEL_PATH)


def _unload() -> None:
    global _model
    _model = None
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:  # noqa: BLE001
        pass


def _generate(prompt: str, w: int, h: int, seed: int, steps: int) -> tuple[Path, float]:
    global _model, _loaded_at
    t0 = time.monotonic()
    if _model is None:
        _model = _load()
        _loaded_at = time.time()
    img = _model.generate_image(seed=seed, prompt=prompt, num_inference_steps=steps, width=w, height=h)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.png"
    img.save(path=str(path), export_json_metadata=False)
    # Small JPEG next to the PNG: this is what gets shown to the vision model (a full 1024px PNG is megabytes).
    pil = img.image.convert("RGB")
    pil.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    pil.save(path.with_suffix(".preview.jpg"), "JPEG", quality=85)
    gc.collect()
    return path, time.monotonic() - t0


@app.post("/v1/images/generations")
async def generations(req: GenRequest) -> dict:
    global _last_used
    w, h = parse_size(req.size)
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    async with _lock:                                   # one image at a time; callers queue
        try:
            path, secs = await asyncio.to_thread(_generate, req.prompt, w, h, seed, req.steps or DEFAULT_STEPS)
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        _last_used = time.monotonic()
    return {"created": int(time.time()),
            "data": [{"path": str(path), "preview_path": str(path.with_suffix(".preview.jpg")), "seed": seed, "width": w, "height": h, "seconds": round(secs, 1)}]}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "loaded": _model is not None, "model_path": MODEL_PATH,
            "model_present": Path(MODEL_PATH).exists(), "idle_unload_s": IDLE_S}


async def _reaper() -> None:
    while True:
        await asyncio.sleep(15)
        if _model is not None and not _lock.locked() and time.monotonic() - _last_used > IDLE_S:
            async with _lock:
                if _model is not None and time.monotonic() - _last_used > IDLE_S:
                    await asyncio.to_thread(_unload)


@app.on_event("startup")
async def _startup() -> None:
    global _last_used
    _last_used = time.monotonic()
    asyncio.create_task(_reaper())


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

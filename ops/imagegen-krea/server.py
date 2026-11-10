"""Local Krea 2 Turbo image service for Atom: LUSTIFY V10 (a Krea 2 Turbo finetune) on MLX via mflux.

Runs in its own environment (ops/imagegen-krea/.venv). Same wire contract as ops/imagegen (Z-Image) and
ops/imagegen-sdxl: loads the model on the first request, frees it after IMAGEGEN_KREA_IDLE_S seconds idle,
one image at a time. Krea 2 Turbo is distilled for about 8 steps with guidance 1 and takes plain English prompts
(its text encoder is Qwen3-VL), so there is no negative prompt, CFG or sampler. No content filter is applied.

    cd ops/imagegen-krea && uv run python server.py          # http://127.0.0.1:8092

POST /v1/images/generations   {"prompt": "...", "model": "lustify", "size": "1024x1024", "seed": 1, "steps": 8}
    -> {"data": [{"path": "<abs png>", "preview_path": "<abs jpg>", "model": "lustify", "seed": 1,
                  "width": 1024, "height": 1024, "seconds": 41.2}]}
GET  /v1/models   GET /health
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
MODEL_ID = "lustify"
def _default_model_path() -> str:
    """The 4-bit folder when it exists (same speed, about 6 GB less memory), otherwise the 8-bit one."""
    for name in ("lustify-v10-q4", "lustify-v10-q8"):
        if (ROOT / "data" / "models" / name).is_dir():
            return str(ROOT / "data" / "models" / name)
    return str(ROOT / "data" / "models" / "lustify-v10-q4")


MODEL_PATH = os.environ.get("IMAGEGEN_KREA_MODEL") or _default_model_path()
OUT_DIR = Path(os.environ.get("IMAGEGEN_KREA_OUT", str(ROOT / "data" / "images")))
IDLE_S = int(os.environ.get("IMAGEGEN_KREA_IDLE_S", "300"))
HOST = os.environ.get("IMAGEGEN_KREA_HOST", "127.0.0.1")
PORT = int(os.environ.get("IMAGEGEN_KREA_PORT", "8092"))
MIN_SIDE, MAX_SIDE, MAX_PIXELS = 256, 1536, 1536 * 1536
PREVIEW_SIDE = 768
DEFAULT_STEPS = 8
ABOUT = "LUSTIFY V10 (Krea 2 Turbo finetune): photoreal incl. adult content. Plain English, 8 steps, no negative prompt."

app = FastAPI(title="atom-imagegen-krea")
_model = None
_last_used = 0.0
_lock = asyncio.Lock()


class GenRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    size: str = "1024x1024"
    seed: int | None = None
    steps: int | None = Field(default=None, ge=1, le=30)
    n: int = Field(default=1, ge=1, le=1)      # accepted for OpenAI compatibility; one image per call
    image: str | None = Field(default=None, max_length=24_000_000)   # base64 start image (image-to-image)
    strength: float = Field(default=0.6, ge=0.05, le=0.95)            # how much to change it: low keeps it, high repaints


def parse_size(size: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{3,4})\s*[x×]\s*(\d{3,4})\s*", size or "")
    if not m:
        raise HTTPException(422, "size must look like 1024x1024")
    w, h = (int(m[1]) // 16 * 16, int(m[2]) // 16 * 16)     # the transformer works on multiples of 16
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE) or w * h > MAX_PIXELS:
        raise HTTPException(422, f"size out of range: each side {MIN_SIDE}-{MAX_SIDE}, at most {MAX_PIXELS} pixels")
    return w, h


def prepare_init_image(data: str, w: int, h: int):
    """Decode the caller's base64 image, apply its EXIF rotation, cover-crop to the target aspect and resize to w x h."""
    import base64
    import binascii
    import io

    from PIL import Image, ImageOps
    raw = data.split(",", 1)[1] if data.startswith("data:") else data
    try:
        img = Image.open(io.BytesIO(base64.b64decode(raw)))
        if img.width * img.height > 64_000_000:
            raise HTTPException(422, "image is too large (over 64 megapixels)")
        img.load()
    except (binascii.Error, ValueError, OSError) as e:
        raise HTTPException(422, "image must be a base64-encoded PNG, JPEG or WebP") from e
    return ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), (w, h), Image.LANCZOS)


def check_model(name: str | None) -> None:
    key = (name or "").strip().lower()
    if key not in ("", "default", MODEL_ID):
        raise HTTPException(404, f"unknown model '{name}'; available: {MODEL_ID}")


def _load():
    if not Path(MODEL_PATH).is_dir():
        raise RuntimeError(f"model folder not found: {MODEL_PATH} (build it with ops/imagegen-krea/convert.py)")
    from mflux.models.common.config import ModelConfig
    from mflux.models.krea2.variants.txt2img.krea2 import Krea2
    return Krea2(model_config=ModelConfig.krea2(), model_path=MODEL_PATH)


def _unload() -> None:
    global _model
    _model = None
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:  # noqa: BLE001
        pass


def _generate(prompt: str, w: int, h: int, seed: int, steps: int, init=None, strength: float = 0.6) -> tuple[Path, float]:
    global _model
    t0 = time.monotonic()
    if _model is None:
        _model = _load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    extra = {}
    tmp = None
    if init is not None:               # mflux's image_strength is how much of the picture to keep (1 - our change amount)
        tmp = OUT_DIR / f".init-{uuid.uuid4().hex[:8]}.png"
        init.save(tmp)
        extra = {"image_path": str(tmp), "image_strength": round(1.0 - strength, 3)}
    try:
        img = _model.generate_image(seed=seed, prompt=prompt, num_inference_steps=steps, width=w, height=h,
                                    guidance=1.0, **extra)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.png"
    img.save(path=str(path), export_json_metadata=False)
    pil = img.image.convert("RGB")
    pil.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    pil.save(path.with_suffix(".preview.jpg"), "JPEG", quality=85)
    gc.collect()
    return path, time.monotonic() - t0


@app.post("/v1/images/generations")
async def generations(req: GenRequest) -> dict:
    global _last_used
    check_model(req.model)
    w, h = parse_size(req.size)
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    init = prepare_init_image(req.image, w, h) if req.image else None
    async with _lock:                                   # one image at a time; callers queue
        try:
            path, secs = await asyncio.to_thread(_generate, req.prompt, w, h, seed, req.steps or DEFAULT_STEPS, init,
                                                 req.strength)
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        _last_used = time.monotonic()
    return {"created": int(time.time()),
            "data": [{"path": str(path), "preview_path": str(path.with_suffix(".preview.jpg")), "model": MODEL_ID,
                      "seed": seed, "width": w, "height": h, "seconds": round(secs, 1)}]}


@app.get("/v1/models")
async def models() -> dict:
    return {"default": MODEL_ID, "data": [
        {"id": MODEL_ID, "style": "natural", "about": ABOUT, "present": Path(MODEL_PATH).is_dir(),
         "loaded": _model is not None,
         "defaults": {"steps": DEFAULT_STEPS, "cfg": None, "sampler": None, "prefix": "", "negative": ""}}]}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "loaded": _model is not None, "model_path": MODEL_PATH,
            "model_present": Path(MODEL_PATH).is_dir(), "idle_unload_s": IDLE_S}


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

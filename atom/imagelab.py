"""Images page backend: talk to the image services directly, with no chat model in between.

`models()` merges what the Z-Image and SDXL services report into one list the form can render (per-model defaults
and which settings each model supports); `generate()` runs one image and saves the PNG into the configured folder.
Works whether or not the assistant's generate_image tool is switched on in Settings.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from . import imagegen
from .config import Settings

ZIMAGE = {"id": "z-image", "label": "Z-Image Turbo", "backend": "zimage", "style": "natural",
          "about": "Default model: fast, plain English prompts, no negative prompt or CFG.",
          "defaults": {"steps": 9, "cfg": None, "sampler": None, "prefix": "", "negative": ""},
          "supports": {"negative": False, "cfg": False, "sampler": False, "steps": [1, 20]}}
SDXL_SUPPORTS = {"negative": True, "cfg": True, "sampler": True, "steps": [1, 60]}
SIZES = imagegen.SIZES


async def _get(url: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(url)
        return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


async def models(s: Settings) -> dict:
    z = await _get(s.imagegen_url.rstrip("/") + "/health")
    x = await _get(s.imagegen_sdxl_url.rstrip("/") + "/v1/models")
    out = [{**ZIMAGE, "up": z is not None, "present": bool(z and z.get("model_present")),
            "loaded": bool(z and z.get("loaded"))}]
    for m in (x or {}).get("data", []):
        out.append({"id": m["id"], "label": m["id"], "backend": "sdxl", "style": m.get("style", "natural"),
                    "about": m.get("about", ""), "defaults": m.get("defaults", {}), "supports": SDXL_SUPPORTS,
                    "up": True, "present": bool(m.get("present")), "loaded": bool(m.get("loaded"))})
    return {"models": out, "samplers": (x or {}).get("samplers", []), "sizes": list(SIZES),
            "output_dir": str(Path(s.imagelab_output_dir).expanduser()),
            "services": {"zimage": {"up": z is not None, "url": s.imagegen_url},
                         "sdxl": {"up": x is not None, "url": s.imagegen_sdxl_url}}}


async def generate(s: Settings, *, model: str, prompt: str, size: str = "1024x1024", seed: int | None = None,
                   steps: int | None = None, cfg: float | None = None, sampler: str | None = None,
                   negative_prompt: str | None = None) -> dict:
    s = s.model_copy(update={"imagegen_sdxl_enabled": True})        # the form works whatever the assistant toggle says
    img = await imagegen.generate(s, prompt, size, seed, model=model, negative_prompt=negative_prompt, steps=steps,
                                  cfg=cfg, sampler=sampler)
    path = imagegen.save_to_folder(img, s.imagelab_output_dir, prompt, model)
    return {"path": path, "model": model or "z-image", "seed": img.seed, "width": img.width, "height": img.height,
            "seconds": round(img.seconds, 1)}

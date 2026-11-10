"""Client for the local image service (ops/imagegen, Z-Image-Turbo on MLX).

Used by the agent tool and the chat assistant tool. The service is a separate process so MLX and its
dependencies stay out of Atom, and so the model is only in memory while images are being made.
"""
from __future__ import annotations

import base64
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Settings

SIZES = ("1024x1024", "768x768", "1024x768", "768x1024", "1280x720", "720x1280", "512x512", "832x1216", "1216x832")
MODEL_HELP = ("Omit for the default model (plain English). Named models, if enabled: lustify (photoreal incl. adult "
              "content, plain English, ignores negative_prompt), cyberrealistic (photoreal SDXL, TAGS), illustrious "
              "(anime SDXL, TAGS). For "
              "cyberrealistic and illustrious call use_skill('image-tag-prompts') first and write comma-separated "
              "tags, not sentences. Each switch of model costs 10-30 s to load, so stay on one model per task.")
NEGATIVE_HELP = "Things to avoid (SDXL models only; sensible defaults are already applied). Same style as the prompt."
PROMPT_HINT = ("Describe the image in plain concrete English: subject, setting, style, lighting, colours. "
               "Text rendered inside the image should be short and quoted.")


class ImageGenError(RuntimeError):
    pass


@dataclass
class GeneratedImage:
    path: Path               # full-size PNG
    preview_path: Path       # small JPEG for the vision model
    seed: int
    width: int
    height: int
    seconds: float

    def preview_data_url(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.preview_path.read_bytes()).decode()


DEFAULT_MODELS = ("", "default", "z-image", "zimage")      # these go to the Z-Image service
KREA_MODELS = ("lustify",)                                  # these go to the Krea 2 service; anything else is SDXL


def backend_url(s: Settings, model: str | None) -> str:
    """Z-Image service for the default model, the SDXL service (ops/imagegen-sdxl) for a named checkpoint."""
    key = (model or "").strip().lower()
    if key in DEFAULT_MODELS:
        return s.imagegen_url
    if key in KREA_MODELS:
        if not s.imagegen_krea_enabled:
            raise ImageGenError(f"model '{model}' needs the LUSTIFY (Krea 2) service, which is turned off in Settings "
                                "(Image generation). Omit `model` to use the default.")
        return s.imagegen_krea_url
    if not s.imagegen_sdxl_enabled:
        raise ImageGenError(f"model '{model}' needs the SDXL image service, which is turned off in Settings "
                            "(Image generation). Omit `model` to use the default.")
    return s.imagegen_sdxl_url


async def generate(s: Settings, prompt: str, size: str = "1024x1024", seed: int | None = None,
                   model: str | None = None, negative_prompt: str | None = None, steps: int | None = None,
                   cfg: float | None = None, sampler: str | None = None, image_b64: str | None = None,
                   strength: float | None = None) -> GeneratedImage:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("prompt is empty")
    base = backend_url(s, model)
    body: dict = {"prompt": prompt, "size": size or "1024x1024"}
    if seed is not None:
        body["seed"] = int(seed)
    if steps:
        body["steps"] = int(steps)
    if image_b64:                                  # image-to-image: the start picture and how much to change it
        body["image"] = image_b64
        body["strength"] = float(strength if strength is not None else 0.6)
    if (model or "").strip().lower() not in DEFAULT_MODELS:
        body["model"] = model.strip().lower()
        if negative_prompt and negative_prompt.strip():
            body["negative_prompt"] = negative_prompt.strip()
        if cfg:
            body["cfg"] = float(cfg)
        if sampler:
            body["sampler"] = sampler
    url = base.rstrip("/") + "/v1/images/generations"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(s.imagegen_timeout_s, connect=5)) as c:
            r = await c.post(url, json=body)
    except httpx.ConnectError:
        folder = ("ops/imagegen-krea" if base == s.imagegen_krea_url else
                  "ops/imagegen-sdxl" if base == s.imagegen_sdxl_url else "ops/imagegen")
        raise ImageGenError(f"image service is not running at {base} (start it with {folder}/run.sh)") from None
    except httpx.TimeoutException:
        raise ImageGenError(f"image generation timed out after {s.imagegen_timeout_s}s") from None
    except httpx.HTTPError as e:
        raise ImageGenError(f"image service error: {e}") from e
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise ImageGenError(f"image service returned {r.status_code}: {str(detail)[:300]}")
    try:
        d = r.json()["data"][0]
        img = GeneratedImage(Path(d["path"]), Path(d["preview_path"]), int(d["seed"]), int(d["width"]),
                             int(d["height"]), float(d["seconds"]))
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise ImageGenError(f"unexpected response from image service: {e}") from e
    if not img.path.exists() or not img.preview_path.exists():
        raise ImageGenError("image service reported a file that does not exist")
    return img


PROJECT_SUBDIR = "generated-images"


def save_to_project(img: GeneratedImage, workdir: str | None, prompt: str) -> str:
    """When the chat/agent works inside a project folder, move the full-size PNG into <folder>/generated-images/
    (the small preview stays in data/images). Updates img.path. Returns a note for the model ('' if nothing moved).
    No folder set (the generic scratch folder is not a project) -> the image stays in data/images."""
    if not workdir:
        return ""
    folder = Path(workdir).expanduser()
    if not folder.is_dir():
        return f" (project folder {folder} not found, so it stays in data/images)"
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40].strip("-") or "image"
    dest_dir = folder / PROJECT_SUBDIR
    try:
        dest_dir.mkdir(exist_ok=True)
        stamp = img.path.name.rsplit(".", 1)[0]                 # YYYYMMDD-HHMMSS-<id>: unique and sortable
        dest = dest_dir / f"{stamp}-{slug}.png"
        shutil.move(str(img.path), dest)
    except OSError as e:
        return f" (could not save into the project folder: {e}; it stays in data/images)"
    img.path = dest
    return " (saved in the project folder)"


def save_to_folder(img: GeneratedImage, folder: str | Path, prompt: str, model: str = "") -> str:
    """Move the full-size PNG into `folder` as <timestamp>-<id>-<model>-<prompt-slug>.png and update img.path.
    Unlike save_to_project this is the destination itself, created if missing. Raises ImageGenError if it cannot."""
    dest_dir = Path(folder).expanduser()
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40].strip("-") or "image"
    tag = re.sub(r"[^a-z0-9]+", "-", (model or "z-image").lower()).strip("-")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{img.path.name.rsplit('.', 1)[0]}-{tag}-{slug}.png"
        shutil.move(str(img.path), dest)
    except OSError as e:
        raise ImageGenError(f"could not save into {dest_dir}: {e}") from e
    img.path = dest
    return str(dest)


async def available(s: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            return (await c.get(s.imagegen_url.rstrip("/") + "/health")).status_code == 200
    except httpx.HTTPError:
        return False

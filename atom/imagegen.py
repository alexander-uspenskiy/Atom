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

SIZES = ("1024x1024", "768x768", "1024x768", "768x1024", "1280x720", "720x1280", "512x512")
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


async def generate(s: Settings, prompt: str, size: str = "1024x1024", seed: int | None = None) -> GeneratedImage:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("prompt is empty")
    body: dict = {"prompt": prompt, "size": size or "1024x1024"}
    if seed is not None:
        body["seed"] = int(seed)
    url = s.imagegen_url.rstrip("/") + "/v1/images/generations"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(s.imagegen_timeout_s, connect=5)) as c:
            r = await c.post(url, json=body)
    except httpx.ConnectError:
        raise ImageGenError(f"image service is not running at {s.imagegen_url} "
                            "(start it with ops/imagegen/run.sh)") from None
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


async def available(s: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            return (await c.get(s.imagegen_url.rstrip("/") + "/health")).status_code == 200
    except httpx.HTTPError:
        return False

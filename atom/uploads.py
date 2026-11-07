"""Image uploads for chat and agent runs.

Images are stored as files under data/uploads and referenced everywhere else by id (conversation messages and run
configs keep only ids). When a prompt is built the files are inlined as OpenAI-style `image_url` data URLs, which
llama-server decodes when it was started with a vision projector (`--mmproj`).
"""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path
from typing import Any

from .stores import Invalid, NotFound

MAX_BYTES = 12 * 1024 * 1024
MAX_PER_MESSAGE = 6
_ID = re.compile(r"^[0-9a-f]{16}$")
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
_DATA_URL = re.compile(r"^data:(image/[a-z+.-]+);base64,(.*)$", re.S)


def sniff(data: bytes) -> str | None:
    """Detect the image type from magic bytes (never trust the client's content type)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class UploadStore:
    def __init__(self, root: Path):
        self.root = root

    def save(self, data: bytes, name: str = "") -> dict:
        if not data:
            raise Invalid("empty image")
        if len(data) > MAX_BYTES:
            raise Invalid(f"image too large ({len(data) // 1024 // 1024} MB, max {MAX_BYTES // 1024 // 1024} MB)")
        mime = sniff(data)
        if not mime:
            raise Invalid("unsupported image type (use PNG, JPEG, GIF or WebP)")
        self.root.mkdir(parents=True, exist_ok=True)
        uid = uuid.uuid4().hex[:16]
        (self.root / f"{uid}.{_EXT[mime]}").write_bytes(data)
        return {"id": uid, "mime": mime, "size": len(data), "name": name[:120]}

    def save_data_url(self, data_url: str, name: str = "") -> dict:
        m = _DATA_URL.match(data_url or "")
        if not m:
            raise Invalid("expected a base64 data URL (data:image/...;base64,...)")
        try:
            raw = base64.b64decode(m.group(2), validate=False)
        except ValueError as e:
            raise Invalid(f"invalid base64: {e}") from e
        return self.save(raw, name)

    def path(self, uid: str) -> Path:
        if not _ID.match(uid or ""):
            raise NotFound("image not found")
        for ext in _EXT.values():
            p = self.root / f"{uid}.{ext}"
            if p.exists():
                return p
        raise NotFound("image not found")

    def validate(self, ids: Any) -> list[str]:
        """Check a client-supplied id list; returns clean ids or raises Invalid."""
        if ids in (None, ""):
            return []
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise Invalid("images must be a list of upload ids")
        if len(ids) > MAX_PER_MESSAGE:
            raise Invalid(f"at most {MAX_PER_MESSAGE} images per message")
        for i in ids:
            self.path(i)            # raises NotFound for unknown ids
        return list(dict.fromkeys(ids))

    def data_url(self, uid: str) -> str:
        p = self.path(uid)
        mime = next(m for m, e in _EXT.items() if e == p.suffix[1:])
        return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"

    def content(self, text: str, ids: list[str] | None) -> str | list[dict]:
        """OpenAI message content: plain string without images, text + image_url parts with them.
        An image file that has disappeared is replaced by a text note instead of failing the whole turn."""
        if not ids:
            return text
        parts: list[dict] = [{"type": "text", "text": text or "(image)"}]
        for uid in ids:
            try:
                parts.append({"type": "image_url", "image_url": {"url": self.data_url(uid)}})
            except NotFound:
                parts.append({"type": "text", "text": "[an attached image is no longer available]"})
        return parts

"""ops/imagegen (Z-Image) service: the image-to-image fields. mflux is not installed in Atom's environment, so
generation is stubbed."""
from __future__ import annotations

import base64
import importlib.util
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

SERVER = Path(__file__).resolve().parent.parent / "ops" / "imagegen" / "server.py"


@pytest.fixture
def zimage(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("imagegen_zimage_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "out")
    return mod


def test_image_to_image_fields(zimage, tmp_path, monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (64, 32), (1, 2, 3)).save(buf, "PNG")
    seen = {}

    def fake(prompt, w, h, seed, steps, init=None, strength=0.6):
        seen.update(init=init, strength=strength, size=(w, h))
        png = tmp_path / "z.png"
        png.write_bytes(b"png")
        return png, 1.0

    monkeypatch.setattr(zimage, "_generate", fake)
    with TestClient(zimage.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "x", "size": "768x1024", "strength": 0.5,
                                                   "image": base64.b64encode(buf.getvalue()).decode()})
        assert r.status_code == 200 and seen["init"].size == (768, 1024) and seen["strength"] == 0.5
        c.post("/v1/images/generations", json={"prompt": "x"})
        assert seen["init"] is None
        assert c.post("/v1/images/generations", json={"prompt": "x", "image": "###"}).status_code == 422
        assert c.post("/v1/images/generations", json={"prompt": "x", "strength": 0.99}).status_code == 422

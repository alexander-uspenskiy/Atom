"""ops/imagegen-krea service: model check, size rules, endpoint contract and error paths. mflux is not installed in
Atom's environment, so generation is stubbed; the real model needs the converted weights (ops/imagegen-krea/README.md)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parent.parent / "ops" / "imagegen-krea" / "server.py"
CONVERT = Path(__file__).resolve().parent.parent / "ops" / "imagegen-krea" / "convert.py"


@pytest.fixture
def krea(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("imagegen_krea_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "MODEL_PATH", str(tmp_path / "lustify-v10-q8"))
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "out")
    return mod


def test_model_check_and_sizes(krea):
    for ok in (None, "", "default", "LUSTIFY"):
        krea.check_model(ok)
    with pytest.raises(HTTPException) as e:
        krea.check_model("pony")
    assert e.value.status_code == 404 and "lustify" in e.value.detail
    assert krea.parse_size("1024x1024") == (1024, 1024) and krea.parse_size("1230x834") == (1216, 832)
    for bad in ("abc", "128x128", "2048x1024", "1536x1536x"):
        with pytest.raises(HTTPException):
            krea.parse_size(bad)


def test_endpoint_contract(krea, tmp_path, monkeypatch):
    seen = {}

    def fake(prompt, w, h, seed, steps, init=None, strength=0.6):
        seen.update(prompt=prompt, size=(w, h), seed=seed, steps=steps, init=init, strength=strength)
        png = tmp_path / "k.png"
        png.write_bytes(b"png")
        return png, 2.5

    monkeypatch.setattr(krea, "_generate", fake)
    with TestClient(krea.app) as c:
        d = c.post("/v1/images/generations", json={"prompt": "a fox", "model": "lustify", "seed": 3}).json()["data"][0]
        assert d["model"] == "lustify" and d["seed"] == 3 and seen["steps"] == 8 and seen["prompt"] == "a fox"
        assert c.post("/v1/images/generations", json={"prompt": "a fox", "steps": 12}).status_code == 200 and seen["steps"] == 12
        assert c.post("/v1/images/generations", json={"prompt": "x", "model": "nope"}).status_code == 404
        assert c.post("/v1/images/generations", json={"prompt": "x", "steps": 99}).status_code == 422


def test_missing_model_folder_is_a_clear_503_and_models_listing(krea):
    with TestClient(krea.app) as c:
        m = c.get("/v1/models").json()["data"][0]
        assert m["id"] == "lustify" and m["present"] is False and m["defaults"]["steps"] == 8 and m["style"] == "natural"
        r = c.post("/v1/images/generations", json={"prompt": "x"})
        assert r.status_code == 503 and "convert.py" in r.json()["detail"]
        assert c.get("/health").json()["model_present"] is False


def test_converter_refuses_missing_inputs(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("imagegen_krea_convert", CONVERT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["convert.py", "--fp8", str(tmp_path / "x.safetensors"), "--base", str(tmp_path),
                                      "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as e:
        mod.main()
    assert "missing" in str(e.value) and "vae" in str(e.value)       # base folder checked before anything heavy runs


def test_image_to_image_resizes_start_image_and_validates(krea, tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (30, 50), (10, 200, 10)).save(buf, "PNG")
    seen = {}

    def fake(prompt, w, h, seed, steps, init=None, strength=0.6):
        seen.update(init=init, strength=strength)
        png = tmp_path / "k2.png"
        png.write_bytes(b"png")
        return png, 1.0

    monkeypatch.setattr(krea, "_generate", fake)
    with TestClient(krea.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "x", "size": "576x832", "strength": 0.3,
                                                   "image": base64.b64encode(buf.getvalue()).decode()})
        assert r.status_code == 200 and seen["init"].size == (576, 832) and seen["strength"] == 0.3
        assert c.post("/v1/images/generations", json={"prompt": "x", "image": "###"}).status_code == 422

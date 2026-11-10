"""ops/imagegen-sdxl service: registry, prompt helpers, chunking, model selection and error paths.

torch/diffusers are not installed in Atom's environment, so generation itself is stubbed; the real pipeline needs the
checkpoints (see ops/imagegen-sdxl/README.md).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parent.parent / "ops" / "imagegen-sdxl" / "server.py"


@pytest.fixture
def sdxl(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("imagegen_sdxl_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)         # pydantic resolves the request model's annotations here
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "out")
    (tmp_path / "models").mkdir()
    return mod


def words(s: str) -> int:             # fake tokenizer: one token per word
    return len(s.split())


def test_registry_lists_the_sdxl_models(sdxl):
    reg = sdxl.load_registry()
    assert set(reg["models"]) == {"cyberrealistic", "illustrious"} and reg["default"] == "cyberrealistic"
    assert {k: v["style"] for k, v in reg["models"].items()} == {
        "cyberrealistic": "tags", "illustrious": "tags"}
    assert reg["models"]["cyberrealistic"]["prefix"].startswith("score_9")
    for cfg in reg["models"].values():                  # defaults only improve quality, nothing filters content
        assert "nsfw" not in cfg["negative"].lower()


def test_resolve_model(sdxl):
    reg = sdxl.load_registry()
    assert sdxl.resolve_model(reg, None)[0] == "cyberrealistic"
    assert sdxl.resolve_model(reg, " CyberRealistic ")[0] == "cyberrealistic"
    assert sdxl.resolve_model(reg, "sdxl")[0] == "cyberrealistic"
    with pytest.raises(HTTPException) as e:
        sdxl.resolve_model(reg, "dalle")
    assert e.value.status_code == 404 and "illustrious" in e.value.detail


def test_parse_size(sdxl):
    assert sdxl.parse_size("1216x832") == (1216, 832)
    assert sdxl.parse_size("1023x1023") == (1016, 1016)
    for bad in ("abc", "256x256", "2048x2048", "1536x1536"):
        with pytest.raises(HTTPException):
            sdxl.parse_size(bad)


def test_prefix_and_negative_do_not_duplicate_tags(sdxl):
    assert sdxl.apply_prefix("1girl, solo", "masterpiece, best quality, ") == "masterpiece, best quality, 1girl, solo"
    assert sdxl.apply_prefix("Masterpiece, 1girl", "masterpiece, best quality") == "best quality, Masterpiece, 1girl"
    assert sdxl.apply_prefix("a red fox", "") == "a red fox"
    assert sdxl.merge_negative("lowres, blurry", "Blurry, text") == "lowres, blurry, text"
    assert sdxl.merge_negative("lowres", None) == "lowres"


def test_pack_chunks_breaks_between_tags_only(sdxl):
    tags = ", ".join(["tag number %d" % i for i in range(10)])           # 3 words + comma = 4 per tag
    chunks = sdxl.pack_chunks(tags, words, limit=9)                      # two tags fit (8), three do not (12)
    assert len(chunks) == 5 and all(c.count("tag number") == 2 for c in chunks)
    assert ", ".join(chunks) == tags                                    # nothing lost, nothing split mid-tag
    assert sdxl.pack_chunks("", words) == [""] and sdxl.pack_chunks("one, two", words) == ["one, two"]
    assert sdxl.pack_chunks("a b c d e f g h i j k l", words, limit=5) == ["a b c d e f g h i j k l"]  # oversize tag kept


def test_endpoint_selects_model_applies_defaults_and_reports_it(sdxl, tmp_path, monkeypatch):
    seen = {}

    def fake_generate(name, cfg, prompt, negative, w, h, seed, steps, guidance, sampler=None, init=None, strength=0.6):
        seen.update(init=init, strength=strength, sampler=sampler, name=name, prompt=prompt, negative=negative, size=(w, h), seed=seed, steps=steps, cfg=guidance)
        png = tmp_path / "x.png"
        png.write_bytes(b"png")
        return png, 1.5

    monkeypatch.setattr(sdxl, "_generate", fake_generate)
    with TestClient(sdxl.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "1girl, solo", "model": "cyberrealistic", "seed": 5,
                                                   "negative_prompt": "text, hat", "size": "832x1216"})
        assert r.status_code == 200
        d = r.json()["data"][0]
        assert d["model"] == "cyberrealistic" and d["seed"] == 5 and (d["width"], d["height"]) == (832, 1216)
        assert seen["name"] == "cyberrealistic" and seen["prompt"].startswith("score_9, score_8_up, score_7_up, 1girl")
        assert seen["negative"].endswith("hat") and seen["negative"].count("text") == 1
        assert seen["steps"] == 30 and seen["cfg"] == 5.0
        r = c.post("/v1/images/generations", json={"prompt": "a fox", "steps": 12, "cfg": 3.0, "sampler": "euler_a"})
        assert seen["name"] == "cyberrealistic" and seen["prompt"].endswith(", a fox") and seen["steps"] == 12 and seen["cfg"] == 3.0 and seen["sampler"] == "euler_a"
        assert c.post("/v1/images/generations", json={"prompt": "x", "model": "nope"}).status_code == 404
        assert c.post("/v1/images/generations", json={"prompt": "x", "sampler": "ddim"}).status_code == 422
        assert c.post("/v1/images/generations", json={"prompt": "x", "size": "10x10"}).status_code == 422


def test_missing_checkpoint_is_a_clear_503(sdxl):
    with TestClient(sdxl.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "x", "model": "illustrious"})
        assert r.status_code == 503 and "illustrious-xl.safetensors" in r.json()["detail"]


def test_models_endpoint_shows_which_checkpoints_are_present(sdxl):
    (sdxl.MODELS_DIR / "cyberrealistic-pony.safetensors").write_bytes(b"x")
    with TestClient(sdxl.app) as c:
        data = {m["id"]: m for m in c.get("/v1/models").json()["data"]}
        assert data["cyberrealistic"]["present"] is True and data["illustrious"]["present"] is False
        assert data["cyberrealistic"]["style"] == "tags" and not any(m["loaded"] for m in data.values())
        d = data["cyberrealistic"]["defaults"]
        assert d["steps"] == 30 and d["sampler"] == "euler_a" and d["prefix"].startswith("score_9") and "score_6" in d["negative"]
        assert c.get("/v1/models").json()["samplers"] == ["euler_a", "dpmpp_2m_karras"]
        assert c.get("/health").json()["loaded"] is None


def _png_b64(w=40, h=20, color=(200, 30, 30)):
    import base64
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_image_to_image_prepares_the_start_image_and_validates(sdxl, tmp_path, monkeypatch):
    seen = {}

    def fake(name, cfg, prompt, negative, w, h, seed, steps, guidance, sampler=None, init=None, strength=0.6):
        seen.update(init=init, strength=strength)
        png = tmp_path / "i.png"
        png.write_bytes(b"png")
        return png, 1.0

    monkeypatch.setattr(sdxl, "_generate", fake)
    with TestClient(sdxl.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "x", "size": "832x1216", "image": _png_b64(), "strength": 0.4})
        assert r.status_code == 200 and seen["init"].size == (832, 1216) and seen["init"].mode == "RGB" and seen["strength"] == 0.4
        c.post("/v1/images/generations", json={"prompt": "x"})
        assert seen["init"] is None
        assert c.post("/v1/images/generations", json={"prompt": "x", "image": "not-an-image"}).status_code == 422
        assert c.post("/v1/images/generations", json={"prompt": "x", "image": _png_b64(), "strength": 1.0}).status_code == 422


def test_start_image_is_cover_cropped_not_stretched(sdxl):
    import base64
    import io

    from PIL import Image
    img = Image.new("RGB", (200, 100), (255, 0, 0))
    img.paste((0, 0, 255), (150, 0, 200, 100))                  # right quarter is blue: lost by a centered 1:1 crop
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = sdxl.prepare_init_image(base64.b64encode(buf.getvalue()).decode(), 64, 64)
    assert out.size == (64, 64) and out.getpixel((5, 32)) == (255, 0, 0) and out.getpixel((60, 32)) == (255, 0, 0)

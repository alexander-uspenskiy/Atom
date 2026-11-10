"""ops/imagegen-sdxl service: registry, prompt helpers, chunking, model selection and error paths.

torch/diffusers are not installed in Atom's environment, so generation itself is stubbed; the real pipeline needs the
checkpoints (see ops/imagegen-sdxl/README.md).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parent.parent / "ops" / "imagegen-sdxl" / "server.py"


@pytest.fixture
def sdxl(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("imagegen_sdxl_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "out")
    (tmp_path / "models").mkdir()
    return mod


def words(s: str) -> int:             # fake tokenizer: one token per word
    return len(s.split())


def test_registry_lists_the_four_models(sdxl):
    reg = sdxl.load_registry()
    assert set(reg["models"]) == {"juggernaut", "realvis", "pony", "illustrious"} and reg["default"] == "juggernaut"
    assert {k: v["style"] for k, v in reg["models"].items()} == {
        "juggernaut": "natural", "realvis": "natural", "pony": "tags", "illustrious": "tags"}
    assert reg["models"]["pony"]["prefix"].startswith("score_9")
    for cfg in reg["models"].values():                  # defaults only improve quality, nothing filters content
        assert "nsfw" not in cfg["negative"].lower()


def test_resolve_model(sdxl):
    reg = sdxl.load_registry()
    assert sdxl.resolve_model(reg, None)[0] == "juggernaut"
    assert sdxl.resolve_model(reg, " Pony ")[0] == "pony"
    assert sdxl.resolve_model(reg, "sdxl")[0] == "juggernaut"
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

    def fake_generate(name, cfg, prompt, negative, w, h, seed, steps, guidance):
        seen.update(name=name, prompt=prompt, negative=negative, size=(w, h), seed=seed, steps=steps, cfg=guidance)
        png = tmp_path / "x.png"
        png.write_bytes(b"png")
        return png, 1.5

    monkeypatch.setattr(sdxl, "_generate", fake_generate)
    with TestClient(sdxl.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "1girl, solo", "model": "pony", "seed": 5,
                                                   "negative_prompt": "text, hat", "size": "832x1216"})
        assert r.status_code == 200
        d = r.json()["data"][0]
        assert d["model"] == "pony" and d["seed"] == 5 and (d["width"], d["height"]) == (832, 1216)
        assert seen["name"] == "pony" and seen["prompt"].startswith("score_9, score_8_up, score_7_up, 1girl")
        assert seen["negative"].endswith("hat") and seen["negative"].count("text") == 1
        assert seen["steps"] == 28 and seen["cfg"] == 7.0
        r = c.post("/v1/images/generations", json={"prompt": "a fox", "steps": 12, "cfg": 3.0})
        assert seen["name"] == "juggernaut" and seen["prompt"] == "a fox" and seen["steps"] == 12 and seen["cfg"] == 3.0
        assert c.post("/v1/images/generations", json={"prompt": "x", "model": "nope"}).status_code == 404
        assert c.post("/v1/images/generations", json={"prompt": "x", "size": "10x10"}).status_code == 422


def test_missing_checkpoint_is_a_clear_503(sdxl):
    with TestClient(sdxl.app) as c:
        r = c.post("/v1/images/generations", json={"prompt": "x", "model": "illustrious"})
        assert r.status_code == 503 and "illustrious-xl.safetensors" in r.json()["detail"]


def test_models_endpoint_shows_which_checkpoints_are_present(sdxl):
    (sdxl.MODELS_DIR / "pony-diffusion-v6-xl.safetensors").write_bytes(b"x")
    with TestClient(sdxl.app) as c:
        data = {m["id"]: m for m in c.get("/v1/models").json()["data"]}
        assert data["pony"]["present"] is True and data["illustrious"]["present"] is False
        assert data["pony"]["style"] == "tags" and not any(m["loaded"] for m in data.values())
        assert c.get("/health").json()["loaded"] is None

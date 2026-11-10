"""generate_image: settings gate, agent tool, chat tool (image shown back to the model), caps and error paths.

The image service itself (ops/imagegen) is replaced by a stub that writes a tiny real PNG/JPEG.
"""
from __future__ import annotations

import base64

import pytest

from atom import imagegen
from atom.tools import ToolContext, build_tools, t_generate_image
from atom.browser.session import ActionError
from tests.conftest import read_sse

# 1x1 PNG / JPEG: just enough for the upload store to sniff them as images
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
JPG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")


@pytest.fixture
def stub(tmp_path, monkeypatch):
    calls: list[dict] = []

    async def fake_generate(s, prompt, size="1024x1024", seed=None, model=None, negative_prompt=None):
        calls.append({"prompt": prompt, "size": size, "seed": seed, "model": model, "negative_prompt": negative_prompt})
        png = tmp_path / f"img{len(calls)}.png"
        jpg = tmp_path / f"img{len(calls)}.preview.jpg"
        png.write_bytes(PNG)
        jpg.write_bytes(JPG)
        return imagegen.GeneratedImage(png, jpg, seed or 7, 1024, 1024, 1.0)

    monkeypatch.setattr(imagegen, "generate", fake_generate)
    return calls


def test_setting_is_off_by_default_and_listed(client):
    vals = client.get("/api/settings").json()["values"]
    assert vals["imagegen_enabled"] is False
    tools = {t["name"]: t for t in client.get("/api/tools").json()}
    assert tools["generate_image"]["enabled"] is False
    client.put("/api/settings", json={"values": {"imagegen_enabled": True}})
    assert {t["name"]: t for t in client.get("/api/tools").json()}["generate_image"]["enabled"] is True


def test_agent_tool_gated_by_setting_and_vision(svc):
    runner = svc.agent_runner
    from atom.agent import RunConfig
    cfg = RunConfig(agent={})
    assert "generate_image" not in runner._tools_for(cfg, vision=True)       # setting off
    runner.update_settings(svc.settings.base.model_copy(update={"imagegen_enabled": True}))
    assert "generate_image" in runner._tools_for(cfg, vision=True)
    assert "generate_image" not in runner._tools_for(cfg, vision=False)      # cannot verify without vision


async def test_tool_returns_image_and_enforces_cap(svc, stub):
    s = svc.settings.base.model_copy(update={"imagegen_enabled": True, "imagegen_max_per_run": 2})
    ctx = ToolContext(session=None, llm=None, settings=s)
    out = await t_generate_image(ctx, {"prompt": "a red fox", "size": "768x768", "seed": 3})
    assert out.ok and len(out.images) == 1 and out.images[0].startswith("data:image/jpeg;base64,")
    assert "seed 3" in out.text and "1 left" in out.text
    await t_generate_image(ctx, {"prompt": "a red fox, snow"})
    with pytest.raises(ActionError, match="limit"):
        await t_generate_image(ctx, {"prompt": "again"})
    assert [c["prompt"] for c in stub] == ["a red fox", "a red fox, snow"]


async def test_tool_reports_service_down(svc):
    s = svc.settings.base.model_copy(update={"imagegen_url": "http://127.0.0.1:9", "imagegen_timeout_s": 5})
    ctx = ToolContext(session=None, llm=None, settings=s)
    with pytest.raises(ActionError, match="not running"):
        await t_generate_image(ctx, {"prompt": "a fox"})


def test_registry_has_tool_with_required_prompt():
    spec = build_tools()["generate_image"]
    assert spec.required == ["prompt"] and spec.side_effect is True


def test_chat_generates_and_model_sees_the_image(client, fake, stub):
    client.put("/api/settings", json={"values": {"imagegen_enabled": True}})
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("generate_image", {"prompt": "a lighthouse at dusk"})]},
              {"calls": [("generate_image", {"prompt": "a lighthouse at dusk, warm light in the window"})]},
              {"content": "Done."})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "draw a lighthouse"})
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [True, True] and "generated_image:" in results[0]["result"]
    assert events[-1]["type"] == "done" and len(stub) == 2
    assert "generate_image" in fake.calls[0]["tools"]
    assert "You can create images" in fake.calls[0]["messages"][0]["content"]
    # 2nd model call: the first image rides in a user message after the tool result, as an image_url part
    second = fake.calls[1]["messages"]
    assert second[-1]["role"] == "user" and any(p["type"] == "image_url" for p in second[-1]["content"])
    # 3rd call: only the newest image keeps its pixels
    third = fake.calls[2]["messages"]
    with_pixels = [m for m in third if m["role"] == "user" and isinstance(m["content"], list)]
    assert len(with_pixels) == 1 and third[-1] is not None and third[-1]["role"] == "user"


def test_chat_has_no_tool_when_disabled_and_plan_mode_blocks_it(client, fake, stub):
    conv = client.post("/api/conversations", json={}).json()
    read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "hi"})
    assert "generate_image" not in fake.calls[0]["tools"]
    client.put("/api/settings", json={"values": {"imagegen_enabled": True}})
    fake.push({"calls": [("generate_image", {"prompt": "x"})]}, {"content": "ok"})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "draw", "mode": "plan"})
    assert not stub
    assert any(e["type"] == "tool_result" and not e["ok"] for e in events)


def test_chat_image_cap_per_message(client, fake, stub):
    client.put("/api/settings", json={"values": {"imagegen_enabled": True, "imagegen_max_per_run": 1}})
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("generate_image", {"prompt": "a"})]}, {"calls": [("generate_image", {"prompt": "b"})]},
              {"content": "ok"})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "draw"})
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [True, False] and "limit" in results[1]["result"] and len(stub) == 1


async def test_agent_tool_saves_into_project_folder(svc, stub, tmp_path):
    proj = tmp_path / "myproj"
    proj.mkdir()
    s = svc.settings.base.model_copy(update={"imagegen_enabled": True})
    ctx = ToolContext(session=None, llm=None, settings=s, workdir=str(proj))
    out = await t_generate_image(ctx, {"prompt": "A red fox, in snow!"})
    saved = list((proj / "generated-images").glob("*.png"))
    assert len(saved) == 1 and saved[0].name.endswith("-a-red-fox-in-snow.png")
    assert saved[0].read_bytes() == PNG and str(saved[0]) in out.text and "project folder" in out.text
    assert out.images and not (tmp_path / "img1.png").exists()        # moved, not copied


async def test_no_project_folder_keeps_default_location(svc, stub, tmp_path):
    s = svc.settings.base.model_copy(update={"imagegen_enabled": True})
    ctx = ToolContext(session=None, llm=None, settings=s)               # no workdir: not a project
    out = await t_generate_image(ctx, {"prompt": "a fox"})
    assert (tmp_path / "img1.png").exists() and "project folder" not in out.text


async def test_missing_project_folder_falls_back_with_note(svc, stub, tmp_path):
    s = svc.settings.base.model_copy(update={"imagegen_enabled": True})
    ctx = ToolContext(session=None, llm=None, settings=s, workdir=str(tmp_path / "gone"))
    out = await t_generate_image(ctx, {"prompt": "a fox"})
    assert (tmp_path / "img1.png").exists() and "not found" in out.text


def test_chat_in_project_saves_there(client, fake, stub, tmp_path):
    proj = tmp_path / "chatproj"
    proj.mkdir()
    client.put("/api/settings", json={"values": {"imagegen_enabled": True}})
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("generate_image", {"prompt": "a lighthouse at dusk"})]}, {"content": "Done."})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages",
                      {"content": "draw", "workdir": str(proj)})
    res = next(e for e in events if e["type"] == "tool_result")
    saved = list((proj / "generated-images").glob("*.png"))
    assert res["ok"] and len(saved) == 1 and str(saved[0]) in res["result"] and "a-lighthouse-at-dusk" in saved[0].name


async def test_tool_passes_model_and_negative_prompt(svc, stub):
    s = svc.settings.base.model_copy(update={"imagegen_enabled": True, "imagegen_sdxl_enabled": True})
    ctx = ToolContext(session=None, llm=None, settings=s)
    await t_generate_image(ctx, {"prompt": "1girl, solo", "model": "illustrious", "negative_prompt": "text"})
    assert stub[0]["model"] == "illustrious" and stub[0]["negative_prompt"] == "text"


def test_backend_routing_and_disabled_sdxl(svc):
    s = svc.settings.base.model_copy(update={"imagegen_url": "http://z", "imagegen_sdxl_url": "http://x"})
    assert [imagegen.backend_url(s, m) for m in (None, "", "default", "Z-Image")] == ["http://z"] * 4
    with pytest.raises(imagegen.ImageGenError, match="turned off"):
        imagegen.backend_url(s, "cyberrealistic")
    s = s.model_copy(update={"imagegen_sdxl_enabled": True})
    assert imagegen.backend_url(s, "cyberrealistic") == "http://x"
    s = s.model_copy(update={"imagegen_krea_url": "http://k"})
    with pytest.raises(imagegen.ImageGenError, match="Krea 2"):                   # lustify has its own switch
        imagegen.backend_url(s, "lustify")
    assert imagegen.backend_url(s.model_copy(update={"imagegen_krea_enabled": True}), "LUSTIFY") == "http://k"


def test_tool_spec_offers_model_and_new_sizes():
    props = build_tools()["generate_image"].properties
    assert {"model", "negative_prompt", "seed"} <= set(props) and "832x1216" in props["size"]["enum"]
    assert "image-tag-prompts" in props["model"]["description"]


def test_sdxl_settings_default_off_and_listed(client):
    vals = client.get("/api/settings").json()["values"]
    assert vals["imagegen_sdxl_enabled"] is False and vals["imagegen_sdxl_url"].endswith(":8091")
    assert vals["imagegen_krea_enabled"] is False and vals["imagegen_krea_url"].endswith(":8092")


# ---------------------------------------------------------------- Images page (direct, no chat model)
@pytest.fixture
def lab(tmp_path, monkeypatch, client):
    out = tmp_path / "AtomImages"
    out.mkdir()                                              # the folder setting only accepts an existing folder
    r = client.put("/api/settings", json={"values": {"imagelab_output_dir": str(out)}})
    assert r.status_code == 200, r.text                      # never fall back to writing into the real default folder
    calls: list[dict] = []

    async def fake_generate(s, prompt, size="1024x1024", seed=None, model=None, negative_prompt=None, steps=None,
                            cfg=None, sampler=None, image_b64=None, strength=None):
        calls.append({"prompt": prompt, "size": size, "seed": seed, "model": model, "neg": negative_prompt,
                      "steps": steps, "cfg": cfg, "sampler": sampler, "sdxl_on": s.imagegen_sdxl_enabled,
                      "image": image_b64, "strength": strength})
        png = tmp_path / f"gen{len(calls)}.png"
        png.write_bytes(PNG)
        return imagegen.GeneratedImage(png, png, seed or 11, 1024, 1024, 2.0)

    monkeypatch.setattr(imagegen, "generate", fake_generate)
    return out, calls


def test_lab_generate_saves_into_output_folder_and_result_is_previewable(client, lab):
    out, calls = lab
    r = client.post("/api/imagelab/generate", json={
        "model": "illustrious", "prompt": "1girl, solo, rain", "size": "832x1216", "seed": 5, "steps": 20,
        "cfg": 6, "sampler": "euler_a", "negative_prompt": "text"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert calls[0] == {"prompt": "1girl, solo, rain", "size": "832x1216", "seed": 5, "model": "illustrious",
                        "neg": "text", "steps": 20, "cfg": 6.0, "sampler": "euler_a", "sdxl_on": True,
                        "image": None, "strength": None}
    assert d["path"].startswith(str(out)) and d["path"].endswith("-illustrious-1girl-solo-rain.png")
    assert d["seed"] == 5 and d["model"] == "illustrious" and (out.exists() and len(list(out.glob("*.png"))) == 1)
    shown = client.get("/api/local-file", params={"path": d["path"]})            # the clickable path works
    assert shown.status_code == 200 and shown.content == PNG and shown.headers["content-type"] == "image/png"


def test_lab_works_with_the_assistant_toggles_off_and_default_model(client, lab):
    out, calls = lab
    assert client.get("/api/settings").json()["values"]["imagegen_sdxl_enabled"] is False
    r = client.post("/api/imagelab/generate", json={"prompt": "a red fox"})
    assert r.status_code == 200 and r.json()["model"] == "z-image" and "-z-image-a-red-fox.png" in r.json()["path"]
    assert calls[0]["model"] == "" and calls[0]["sdxl_on"] is True


def test_lab_errors_and_preview_stays_sandboxed(client, lab, tmp_path_factory):
    out, calls = lab

    async def boom(*a, **k):
        raise imagegen.ImageGenError("checkpoint for 'lustify' not found")
    import atom.imagegen as ig
    ig.generate = boom
    r = client.post("/api/imagelab/generate", json={"model": "lustify", "prompt": "x"})
    assert r.status_code == 502 and "not found" in r.json()["detail"]
    assert client.post("/api/imagelab/generate", json={"prompt": ""}).status_code == 422
    outside = tmp_path_factory.mktemp("outside") / "elsewhere.png"       # not under data/ or the output folder
    outside.write_bytes(PNG)
    assert client.get("/api/local-file", params={"path": str(outside)}).status_code == 404


def test_lab_models_lists_both_services_with_defaults(client, monkeypatch):
    from atom import imagelab

    async def fake_get(url):
        if url.endswith("/health"):
            return {"ok": True, "loaded": False, "model_present": True}
        if ":8092" in url:
            return {"default": "lustify", "data": [{"id": "lustify", "style": "natural", "about": "krea", "present": True,
                                                    "loaded": True, "defaults": {"steps": 8}}]}
        return {"default": "lustify", "samplers": ["euler_a", "dpmpp_2m_karras"], "data": [
            {"id": "illustrious", "style": "tags", "about": "anime", "present": True, "loaded": False,
             "defaults": {"steps": 28, "cfg": 5.5, "sampler": "euler_a", "prefix": "masterpiece, ", "negative": "bad"}}]}

    monkeypatch.setattr(imagelab, "_get", fake_get)
    d = client.get("/api/imagelab/models").json()
    ids = {m["id"]: m for m in d["models"]}
    assert list(ids) == ["z-image", "illustrious", "lustify"] and d["services"]["sdxl"]["up"] and d["services"]["krea"]["up"] and d["samplers"][0] == "euler_a"
    assert ids["z-image"]["supports"]["negative"] is False and ids["illustrious"]["supports"]["cfg"] is True
    assert ids["lustify"]["backend"] == "krea" and ids["lustify"]["supports"]["negative"] is False and ids["lustify"]["loaded"]
    assert ids["illustrious"]["defaults"]["prefix"] == "masterpiece, " and d["output_dir"].endswith("AtomImages")


def test_lab_models_reports_services_down(client):
    client.put("/api/settings", json={"values": {"imagegen_url": "http://127.0.0.1:9", "imagegen_sdxl_url": "http://127.0.0.1:9",
                                                 "imagegen_krea_url": "http://127.0.0.1:9"}})
    d = client.get("/api/imagelab/models").json()      # nothing listens on port 9
    assert d["models"][0]["id"] == "z-image" and d["models"][0]["up"] is False and d["services"]["sdxl"]["up"] is False
    lus = [m for m in d["models"] if m["id"] == "lustify"][0]               # still listed, so the page can say how to start it
    assert lus["backend"] == "krea" and lus["up"] is False and d["services"]["krea"]["up"] is False


def test_lab_image_to_image_sends_the_upload_and_strength(client, lab):
    out, calls = lab
    up = client.post("/api/uploads?name=start.png", content=PNG, headers={"content-type": "application/octet-stream"})
    assert up.status_code == 201, up.text
    r = client.post("/api/imagelab/generate", json={"model": "lustify", "prompt": "oil painting", "image_id": up.json()["id"],
                                                    "strength": 0.35})
    assert r.status_code == 200, r.text
    assert base64.b64decode(calls[0]["image"]) == PNG and calls[0]["strength"] == 0.35
    assert r.json()["image_to_image"] is True
    plain = client.post("/api/imagelab/generate", json={"model": "lustify", "prompt": "a fox"}).json()
    assert calls[1]["image"] is None and plain["image_to_image"] is False


def test_lab_image_to_image_rejects_bad_uploads_and_strength(client, lab):
    out, calls = lab
    assert client.post("/api/imagelab/generate", json={"prompt": "x", "image_id": "0123456789abcdef"}).status_code == 404
    doc = client.post("/api/uploads?name=notes.txt", content=b"hello there", headers={"content-type": "application/octet-stream"})
    assert doc.status_code == 201 and doc.json()["kind"] == "document"
    r = client.post("/api/imagelab/generate", json={"prompt": "x", "image_id": doc.json()["id"]})
    assert r.status_code == 422 and "not an image" in r.text
    assert client.post("/api/imagelab/generate", json={"prompt": "x", "strength": 1.5}).status_code == 422
    assert not calls


def test_client_sends_image_and_strength_only_when_given(monkeypatch):
    import asyncio
    sent = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"path": "/x.png", "preview_path": "/x.jpg", "seed": 1, "width": 8, "height": 8, "seconds": 1}]}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json): sent.update(url=url, body=json); return FakeResp()

    monkeypatch.setattr(imagegen.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(imagegen.Path, "exists", lambda self: True)
    from atom.config import Settings
    s = Settings(imagegen_krea_enabled=True)
    asyncio.run(imagegen.generate(s, "a fox", model="lustify", image_b64="QUJD", strength=0.4))
    assert sent["url"].endswith(":8092/v1/images/generations") and sent["body"]["image"] == "QUJD" and sent["body"]["strength"] == 0.4
    asyncio.run(imagegen.generate(s, "a fox", model="lustify"))
    assert "image" not in sent["body"] and "strength" not in sent["body"]

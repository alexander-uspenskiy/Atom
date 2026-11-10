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
        imagegen.backend_url(s, "pony")
    s = s.model_copy(update={"imagegen_sdxl_enabled": True})
    assert imagegen.backend_url(s, "pony") == "http://x"


def test_tool_spec_offers_model_and_new_sizes():
    props = build_tools()["generate_image"].properties
    assert {"model", "negative_prompt", "seed"} <= set(props) and "832x1216" in props["size"]["enum"]
    assert "image-tag-prompts" in props["model"]["description"]


def test_sdxl_settings_default_off_and_listed(client):
    vals = client.get("/api/settings").json()["values"]
    assert vals["imagegen_sdxl_enabled"] is False and vals["imagegen_sdxl_url"].endswith(":8091")

"""Image attachments: upload API, chat messages, agent runs, history trimming, DB migration."""
from __future__ import annotations

import base64
import sqlite3

from atom.db import Database

from .conftest import make_local_agent, read_sse, wait_run

# 1x1 transparent PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def upload(client, url: str = PNG_URL) -> dict:
    r = client.post("/api/uploads", json={"data_url": url, "name": "t.png"})
    assert r.status_code == 201, r.text
    return r.json()


def image_parts(msg: dict) -> list[dict]:
    c = msg["content"]
    return [p for p in c if p["type"] == "image_url"] if isinstance(c, list) else []


def test_upload_roundtrip_and_validation(client):
    u = upload(client)
    assert u["mime"] == "image/png" and u["url"] == f"/api/uploads/{u['id']}"
    got = client.get(u["url"])
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    # content type is sniffed, not trusted
    bad = client.post("/api/uploads", json={"data_url": "data:image/png;base64," + base64.b64encode(b"not an image").decode()})
    assert bad.status_code == 422
    assert client.post("/api/uploads", json={"data_url": "hello"}).status_code == 422
    assert client.get("/api/uploads/..%2f..%2fetc%2fpasswd").status_code in (404, 422)
    assert client.get("/api/uploads/0123456789abcdef").status_code == 404


def test_chat_with_image(client, fake):
    cid = client.post("/api/conversations", json={}).json()["id"]
    u = upload(client)
    fake.push({"content": "I see a pixel."})
    evs = read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "what is this?", "images": [u["id"]]})
    assert any(e["type"] == "done" for e in evs)
    sent = fake.calls[-1]["messages"][-1]
    assert sent["role"] == "user" and sent["content"][0] == {"type": "text", "text": "what is this?"}
    assert image_parts(sent)[0]["image_url"]["url"] == PNG_URL
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert msgs[0]["images"] == [u["id"]]


def test_chat_image_only_message_and_unknown_id(client, fake):
    cid = client.post("/api/conversations", json={}).json()["id"]
    u = upload(client)
    fake.push({"content": "ok"})
    read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "", "images": [u["id"]]})
    assert client.get(f"/api/conversations/{cid}").json()["title"] == "Image"
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "x", "images": ["0123456789abcdef"]})
    assert r.status_code == 404
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "", "images": []})
    assert r.status_code == 422


def test_old_images_dropped_from_history(client, fake):
    cid = client.post("/api/conversations", json={}).json()["id"]
    ids = [upload(client)["id"] for _ in range(4)]
    for i in ids:
        fake.push({"content": "ok"})
        read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": f"look {i}", "images": [i]})
    users = [m for m in fake.calls[-1]["messages"] if m["role"] == "user"]
    with_pixels = [m for m in users if image_parts(m)]
    assert len(with_pixels) == 2 and image_parts(users[-1])
    assert "omitted" in users[0]["content"]


def test_run_with_image(client, fake, site):
    agent = make_local_agent(client)
    u = upload(client)
    r = client.post(f"/api/agents/{agent['id']}/run", json={"task": "read the attached image", "images": [u["id"]]})
    assert r.status_code == 202, r.text
    run = wait_run(client, r.json()["run_id"])
    assert run["images"] == [u["id"]]
    first = fake.calls[0]["messages"][1]
    assert first["role"] == "user" and image_parts(first)
    assert "attached 1 image" in first["content"][0]["text"]


def test_run_without_images_unchanged(client, fake):
    agent = make_local_agent(client)
    r = client.post(f"/api/agents/{agent['id']}/run", json={"task": "plain"})
    run = wait_run(client, r.json()["run_id"])
    assert run["images"] == []
    assert isinstance(fake.calls[0]["messages"][1]["content"], str)


def test_no_vision_server_rejects_images(client, fake):
    async def no_vision():
        return False
    fake.vision = no_vision
    cid = client.post("/api/conversations", json={}).json()["id"]
    u = upload(client)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "x", "images": [u["id"]]})
    assert r.status_code == 422 and "vision" in r.json()["detail"]
    agent = make_local_agent(client)
    r = client.post(f"/api/agents/{agent['id']}/run", json={"task": "x", "images": [u["id"]]})
    assert r.status_code == 422


def test_assistant_forwards_images_to_run(client, fake):
    agent = make_local_agent(client)
    cid = client.post("/api/conversations", json={}).json()["id"]
    u = upload(client)
    fake.push({"calls": [("run_agent", {"agent": agent["name"], "task": "describe the image", "attach_images": True})]},
              {"content": "started"})
    evs = read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "have an agent read this", "images": [u["id"]]})
    rid = next(e["run_id"] for e in evs if e["type"] == "run_started")
    assert wait_run(client, rid)["images"] == [u["id"]]


def test_migration_adds_images_column(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL, "
              "content TEXT, reasoning TEXT, tool_calls TEXT, tool_call_id TEXT, action_id TEXT, run_id TEXT, stats TEXT, created_at REAL)")
    c.commit()
    c.close()
    db = Database(p)
    assert "images" in {r["name"] for r in db.all("PRAGMA table_info(messages)")}
    db.close()

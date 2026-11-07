"""Telegram connector: config, tools and the chat bridge, against a fake Bot API (no network)."""
import asyncio
import json

import httpx
import pytest

from atom.assistant import Assistant
from atom.connectors import telegram as tg

TOKEN = "123456789:" + "A" * 35


class FakeTelegram:
    """Just enough of the Bot API: queued updates in, recorded calls out."""

    def __init__(self):
        self.updates: list[dict] = []
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 1
        self.file_content: bytes | None = None        # what the file endpoint serves (default: a tiny PNG)

    def push_document(self, uid: int, name: str, mime: str, caption: str | None = None) -> None:
        m = {"message_id": self.next_id, "from": {"id": uid, "is_bot": False}, "chat": {"id": uid, "type": "private"},
             "document": {"file_id": "docfile", "file_name": name, "mime_type": mime}}
        if caption:
            m["caption"] = caption
        self.updates.append({"update_id": self.next_id, "message": m})
        self.next_id += 1

    def push_message(self, uid: int, text: str, chat_type: str = "private") -> None:
        self.updates.append({"update_id": self.next_id, "message": {
            "message_id": self.next_id, "from": {"id": uid, "is_bot": False}, "chat": {"id": uid, "type": chat_type},
            "text": text}})
        self.next_id += 1

    def push_callback(self, uid: int, data: str) -> None:
        self.updates.append({"update_id": self.next_id, "callback_query": {
            "id": f"cb{self.next_id}", "from": {"id": uid}, "data": data,
            "message": {"message_id": 99, "chat": {"id": uid}, "text": "Proposal: x"}}})
        self.next_id += 1

    def push_photo(self, uid: int, caption: str | None = None, document: bool = False) -> None:
        m = {"message_id": self.next_id, "from": {"id": uid, "is_bot": False}, "chat": {"id": uid, "type": "private"}}
        if document:
            m["document"] = {"file_id": "doc1", "mime_type": "image/png"}
        else:
            m["photo"] = [{"file_id": "small", "file_size": 10, "width": 1, "height": 1},
                          {"file_id": "big", "file_size": 99, "width": 2, "height": 2}]
        if caption:
            m["caption"] = caption
        self.updates.append({"update_id": self.next_id, "message": m})
        self.next_id += 1

    def sent(self, method: str = "sendMessage") -> list[dict]:
        return [p for m, p in self.calls if m == method]

    PNG = (b"\x89PNG\r\n\x1a\n" + b"\0" * 32)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if "/file/bot" in request.url.path:                       # file download endpoint
            self.calls.append(("download", {"path": request.url.path}))
            return httpx.Response(200, content=self.file_content or self.PNG)
        method = request.url.path.rsplit("/", 1)[-1]
        ctype = request.headers.get("content-type", "")
        params = json.loads(request.content or b"{}") if ctype.startswith("application/json") or not request.content else {"multipart": True}
        self.calls.append((method, params))
        if method == "sendPhoto":                                 # multipart upload: keep the raw body for assertions
            self.calls[-1] = (method, {"multipart": request.content, "type": request.headers["content-type"]})
            return httpx.Response(200, json={"ok": True, "result": True})
        if method == "getFile":
            return httpx.Response(200, json={"ok": True, "result": {"file_id": params["file_id"], "file_size": 40,
                                                                    "file_path": f"photos/{params['file_id']}.png"}})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 555, "username": "atom_test_bot"}})
        if method in ("getMyDescription", "getMyShortDescription"):
            return httpx.Response(200, json={"ok": True, "result": {"description": "", "short_description": ""}})
        if method == "getUpdates":
            if self.updates:
                ups, self.updates = self.updates, []
                return httpx.Response(200, json={"ok": True, "result": ups})
            return httpx.Response(200, json={"ok": True, "result": []})
        return httpx.Response(200, json={"ok": True, "result": True})


@pytest.fixture
def fake_tg(monkeypatch):
    f = FakeTelegram()

    async def slow(request):                      # emulate long polling so the loop doesn't spin
        if request.url.path.endswith("getUpdates") and not f.updates:
            await asyncio.sleep(0.05)
        return f.handler(request)

    monkeypatch.setattr(tg, "make_client", lambda token: httpx.AsyncClient(
        base_url=f"https://api.telegram.org/bot{token}/", transport=httpx.MockTransport(slow)))
    return f


async def until(cond, timeout=5.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


def save(client, **cfg):
    return client.put("/api/connectors/bot", json={"type": "telegram", "enabled": True, "config": {
        "bot_token": TOKEN, "allowed_user_ids": "42", **cfg}})


def test_config_validation_and_tool(client, svc, fake_tg, _memory_keyring):
    assert client.put("/api/connectors/bot", json={"type": "telegram", "config": {"bot_token": "nope"}}).status_code == 422
    assert save(client, allowed_user_ids="abc").status_code == 422
    r = save(client)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["state"] == "ready" and "bot_token" not in item["config"] and item["has_secret"]["bot_token"]
    assert TOKEN not in client.get("/api/connectors").text
    assert TOKEN not in str(svc.db.all("SELECT * FROM connectors")[0]["config"])
    assert _memory_keyring.get_password("atom-connector", "bot:bot_token") == TOKEN
    assert "telegram_bot_send" in {t["name"] for t in client.get("/api/tools").json()}
    # tool is not offered when agents may not message, or when nobody is allowed yet
    save(client, allow_agent_send=False)
    assert "telegram_bot_send" not in {t["name"] for t in client.get("/api/tools").json()}
    save(client, allowed_user_ids="")
    assert "telegram_bot_send" not in {t["name"] for t in client.get("/api/tools").json()}
    assert client.post("/api/connectors/bot/test").json()["ok"] is True


async def test_bridge_chat_auth_and_approval(svc, fake, fake_tg):
    svc.assistant = Assistant(svc)
    br = tg.Bridge("bot", {"allowed_user_ids": "42"}, svc, tg.BotAPI(TOKEN))
    task = asyncio.create_task(br.run())
    try:
        # a stranger only learns their own id, and only once a minute
        await until(lambda: fake_tg.sent("setMyProfilePhoto"))      # profile is filled in on start
        assert fake_tg.sent("setMyDescription")[0]["description"] == tg.DESCRIPTION
        assert fake_tg.sent("setMyShortDescription")[0]["short_description"] == tg.SHORT_DESCRIPTION
        assert len(tg.SHORT_DESCRIPTION) <= 120 and len(tg.DESCRIPTION) <= 512
        fake_tg.push_message(7, "hello")
        fake_tg.push_message(7, "hello again")
        fake_tg.push_message(42, "/help")
        await until(lambda: len(fake_tg.sent()) >= 2)
        texts = [p["text"] for p in fake_tg.sent()]
        assert sum("user ID is 7" in t for t in texts) == 1
        assert any("Atom" in t for t in texts)
        assert not fake.calls                                # the model was never reached for the stranger
        # groups are ignored
        fake_tg.push_message(42, "hi", chat_type="group")
        # a normal turn that proposes a memory -> reply + approval buttons
        fake.push({"calls": [("propose_memory", {"content": "likes tea"})]}, {"content": "Proposed it."})
        fake_tg.push_message(42, "remember I like tea")
        await until(lambda: any(p["text"] == "Proposed it." for p in fake_tg.sent()))
        prop = next(p for p in fake_tg.sent() if p["text"].startswith("Proposal:"))
        aid = prop["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[1]
        # a stranger cannot approve; the owner can
        fake_tg.push_callback(7, f"a:{aid}")
        await until(lambda: fake_tg.sent("answerCallbackQuery"))
        assert svc.action_store.get(aid)["status"] == "pending"
        fake_tg.push_callback(42, f"a:{aid}")
        await until(lambda: len(fake_tg.sent("answerCallbackQuery")) == 2)
        assert svc.action_store.get(aid)["status"] == "approved"
        assert fake_tg.sent("editMessageText")
        # conversation is kept per user; /new starts another one
        convs = [c for c in svc.conversations.list() if c["title"].startswith("Telegram/bot 42")]
        assert len(convs) == 1 and convs[0]["title"] == "Telegram/bot 42"
        fake_tg.push_message(42, "/new")
        fake.push({"content": "fresh"})
        await until(lambda: any("Fresh" in p["text"] for p in fake_tg.sent()))
        fake_tg.push_message(42, "hi")
        await until(lambda: any(p["text"] == "fresh" for p in fake_tg.sent()))
        assert len([c for c in svc.conversations.list() if c["title"] == "Telegram/bot 42"]) == 1
        assert len(svc.conversations.list()) == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_chunks():
    assert tg.chunks("a" * 9000, 4000) == ["a" * 4000, "a" * 4000, "a" * 1000]
    assert tg.chunks("x\n" * 3000, 4000)[0].count("x") <= 2000
    assert tg.chunks("  ") == ["(empty)"]


async def test_bridge_photo_goes_to_assistant(svc, fake, fake_tg):
    svc.assistant = Assistant(svc)
    br = tg.Bridge("bot", {"allowed_user_ids": "42"}, svc, tg.BotAPI(TOKEN))
    task = asyncio.create_task(br.run())
    try:
        fake.push({"content": "A tiny image."}, {"content": "Same, as a file."}, {"content": "caption only"})
        fake_tg.push_photo(42, caption="what is this?")
        await until(lambda: any(p["text"] == "A tiny image." for p in fake_tg.sent()))
        # the largest size is downloaded, and the model gets the caption plus the image
        assert [c[1]["path"] for c in fake_tg.calls if c[0] == "download"] == [f"/file/bot{TOKEN}/photos/big.png"]
        user = fake.calls[0]["messages"][-1]
        assert user["content"][0] == {"type": "text", "text": "what is this?"}
        assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        # an image sent as a document works too, and a photo without caption is still a message
        fake_tg.push_photo(42, document=True)
        await until(lambda: any(p["text"] == "Same, as a file." for p in fake_tg.sent()))
        assert "/file/bot" in [c[1]["path"] for c in fake_tg.calls if c[0] == "download"][-1]
        convs = [c for c in svc.conversations.list() if c["title"] == "Telegram/bot 42"]
        msgs = svc.conversations.get(convs[0]["id"])["messages"]
        assert [m["images"] for m in msgs if m["role"] == "user"][0]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_bridge_photo_without_vision_reports_error(svc, fake, fake_tg):
    async def no_vision():
        return False
    fake.vision = no_vision
    svc.assistant = Assistant(svc)
    br = tg.Bridge("bot", {"allowed_user_ids": "42"}, svc, tg.BotAPI(TOKEN))
    task = asyncio.create_task(br.run())
    try:
        fake_tg.push_photo(42, caption="hi")
        await until(lambda: any("vision" in p["text"] for p in fake_tg.sent()))
        assert not fake.calls
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_assistant_can_send_run_screenshot_to_telegram(svc, fake, fake_tg):
    svc.assistant = Assistant(svc)
    svc.agents.ensure_default()
    agent = svc.agents.default()
    run = svc.runs.create("20261107-000000-abc123", "t", agent=agent, trigger="manual", schedule_id=None, config={},
                          thinking="off", effort="low", run_dir="x")
    shots = svc.settings.effective().runs_dir / run["id"] / "shots"
    shots.mkdir(parents=True)
    (shots / "3.jpg").write_bytes(b"\xff\xd8\xff" + b"JPEGDATA")
    svc.runs.bump(run["id"], last_screenshot=3)
    br = tg.Bridge("bot", {"allowed_user_ids": "42"}, svc, tg.BotAPI(TOKEN))
    task = asyncio.create_task(br.run())
    try:
        fake.push({"calls": [("send_image", {"run_id": run["id"], "caption": "latest page"})]}, {"content": "There you go."})
        fake_tg.push_message(42, "show me the last screenshot")
        await until(lambda: any(p["text"] == "There you go." for p in fake_tg.sent()))
        photo = fake_tg.sent("sendPhoto")[0]
        assert b"JPEGDATA" in photo["multipart"] and b"latest page" in photo["multipart"]
        assert "send_image" in fake.calls[0]["tools"]
        # an unknown run gives the model an error to recover from, nothing is sent
        fake.push({"calls": [("send_image", {"run_id": "nope"})]}, {"content": "No such run."})
        fake_tg.push_message(42, "show run nope")
        await until(lambda: any(p["text"] == "No such run." for p in fake_tg.sent()))
        assert len(fake_tg.sent("sendPhoto")) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_dashboard_chat_does_not_offer_send_image(svc, fake):
    svc.assistant = Assistant(svc)
    cid = svc.conversations.create()["id"]
    fake.push({"content": "ok"})
    async for _ in svc.assistant.converse(cid, "hi"):
        pass
    assert "send_image" not in fake.calls[0]["tools"]


async def test_send_tool_can_attach_a_screenshot(svc, fake_tg, site):
    from atom.browser.session import BrowserSession, Policy
    from atom.tools import ToolContext
    conn = tg.TelegramConnector()
    tools = conn.build_tools("bot", {"bot_token": TOKEN, "allowed_user_ids": "42", "allow_agent_send": True})
    send = tools["telegram_bot_send"]
    assert "include_screenshot" in send.properties
    sess = BrowserSession(svc.settings.effective(), Policy(allow_private=True))
    await sess.start()
    try:
        await sess.goto(site.base + "/")
        ctx = ToolContext(session=sess, llm=None, settings=svc.settings.effective())
        out = await send.handler(ctx, {"text": "Look at this", "include_screenshot": True})
        assert out.ok and "screenshot" in out.text
        photo = fake_tg.sent("sendPhoto")[0]
        assert b"Look at this" in photo["multipart"] and b"JFIF" in photo["multipart"]
        out = await send.handler(ctx, {"text": "plain"})
        assert fake_tg.sent()[-1]["text"] == "plain" and len(fake_tg.sent("sendPhoto")) == 1
    finally:
        await sess.close()


async def test_bridge_document_goes_to_assistant(svc, fake, fake_tg):
    svc.assistant = Assistant(svc)
    br = tg.Bridge("bot", {"allowed_user_ids": "42"}, svc, tg.BotAPI(TOKEN))
    task = asyncio.create_task(br.run())
    try:
        fake_tg.file_content = b"# Notes\nThe launch is on Friday."
        fake.push({"content": "Friday."}, {"content": "unsupported handled"})
        fake_tg.push_document(42, "notes.md", "text/markdown", caption="when is the launch?")
        await until(lambda: any(p["text"] == "Friday." for p in fake_tg.sent()))
        user = fake.calls[0]["messages"][-1]
        assert isinstance(user["content"], str) and user["content"].startswith("when is the launch?")
        assert "The launch is on Friday." in user["content"] and 'document "notes.md"' in user["content"]
        # a file type we cannot read gets a polite message, not a crash
        fake_tg.push_document(42, "data.xls", "application/vnd.ms-excel")
        await until(lambda: any("can read text messages" in p["text"] for p in fake_tg.sent()))
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_file_ref_routing():
    ref = tg.Bridge._file_ref
    assert ref({"document": {"file_id": "a", "file_name": "r.PDF", "mime_type": "application/octet-stream"}}) == ("a", "r.PDF")
    assert ref({"document": {"file_id": "b", "mime_type": "image/png"}}) == ("b", "")
    assert ref({"document": {"file_id": "c", "file_name": "x.xls", "mime_type": "application/vnd.ms-excel"}}) == (None, "")

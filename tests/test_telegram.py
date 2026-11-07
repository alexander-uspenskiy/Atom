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

    def sent(self, method: str = "sendMessage") -> list[dict]:
        return [p for m, p in self.calls if m == method]

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        ctype = request.headers.get("content-type", "")
        params = json.loads(request.content or b"{}") if ctype.startswith("application/json") or not request.content else {"multipart": True}
        self.calls.append((method, params))
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

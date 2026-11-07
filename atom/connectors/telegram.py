"""Telegram connector: chat with Atom from a Telegram bot.

Setup: in Telegram talk to @BotFather, send /newbot, name it "Atom" and pick a username ending in "bot". Paste the token
here (it is kept in the system keychain). The bot long-polls Telegram, so nothing needs to be exposed to the internet.

Security: only the Telegram user IDs listed under "Allowed user IDs" may talk to the bot. Anyone else gets a reply with
their own ID (so you can find yours by messaging the bot once) and nothing more. Private chats only.

Messages go to the dashboard assistant (same conversation as the Chat page, one conversation per user). Anything the
assistant proposes (schedules, agents, ...) shows up as a message with Approve / Reject buttons.
Optional tool for agents: telegram_<name>_send, to message you from a scheduled run.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

from ..browser.session import ActionError
from ..stores import Conflict, Invalid, NotFound
from ..tools import ToolContext, ToolOutput, ToolSpec
from . import Connector, register

log = logging.getLogger("atom.telegram")

API = "https://api.telegram.org"
MAX_LEN = 4000                      # Telegram's limit is 4096
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
COMMANDS = [{"command": "new", "description": "Start a fresh conversation"},
            {"command": "help", "description": "What I can do"}]
HELP = ("I'm Atom, your local web agent. Ask me to browse the web, check on runs, or set up schedules.\n\n"
        "/new - start a fresh conversation\n/help - this message")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_ids(v: Any) -> set[int]:
    out = set()
    for p in re.split(r"[,\s;]+", str(v or "")):
        if not p:
            continue
        if not re.fullmatch(r"\d{1,15}", p):
            raise Invalid(f"'{p}' is not a Telegram user ID (a number like 123456789).")
        out.add(int(p))
    return out


def chunks(text: str, n: int = MAX_LEN) -> list[str]:
    text = text.strip() or "(empty)"
    out = []
    while len(text) > n:
        cut = text.rfind("\n", 0, n)
        cut = cut if cut > n // 2 else n
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    out.append(text)
    return out


class TelegramError(Exception):
    def __init__(self, msg: str, code: int | None = None, retry_after: int | None = None):
        super().__init__(msg)
        self.code, self.retry_after = code, retry_after


def make_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=f"{API}/bot{token}/", timeout=httpx.Timeout(45, connect=10))


class BotAPI:
    """Minimal Bot API client. Never lets the token (part of the URL) leak into error messages."""

    def __init__(self, token: str):
        self.client = make_client(token)

    async def call(self, method: str, **params: Any) -> Any:
        try:
            r = await self.client.post(method, json={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as e:
            raise TelegramError(f"network error ({type(e).__name__})") from None
        try:
            data = r.json()
        except ValueError:
            raise TelegramError(f"unexpected response (HTTP {r.status_code})", r.status_code) from None
        if not data.get("ok"):
            raise TelegramError(data.get("description") or "request failed", data.get("error_code"),
                                (data.get("parameters") or {}).get("retry_after"))
        return data["result"]

    async def send(self, chat_id: int, text: str, **extra: Any) -> None:
        parts = chunks(text)
        for i, part in enumerate(parts):
            await self.call("sendMessage", chat_id=chat_id, text=part, link_preview_options={"is_disabled": True},
                            **(extra if i == len(parts) - 1 else {}))

    async def aclose(self) -> None:
        await self.client.aclose()


class Bridge:
    """One running bot: polls Telegram and forwards messages to the dashboard assistant."""

    def __init__(self, name: str, cfg: dict[str, Any], svc: Any, api: BotAPI):
        self.name, self.svc, self.api = name, svc, api
        self.allowed = parse_ids(cfg.get("allowed_user_ids"))
        self.locks: dict[int, asyncio.Lock] = {}
        self.tasks: set[asyncio.Task] = set()
        self.denied_at: dict[int, float] = {}

    # ------------------------------------------------------------------ polling
    async def run(self) -> None:
        try:
            await self.api.call("deleteWebhook")                    # getUpdates and webhooks are mutually exclusive
            me = await self.api.call("getMe")
            await self.api.call("setMyCommands", commands=COMMANDS)
            log.info("telegram bot @%s connected as '%s'", me.get("username"), self.name)
            offset, delay = None, 1.0
            while True:
                try:
                    updates = await self.api.call("getUpdates", offset=offset, timeout=30,
                                                  allowed_updates=["message", "callback_query"])
                    delay = 1.0
                except TelegramError as e:
                    if e.code in (401, 404):
                        raise TelegramError("Telegram rejected the bot token (revoked or wrong).") from None
                    log.warning("telegram poll error: %s", e)
                    await asyncio.sleep(e.retry_after or delay)
                    delay = min(delay * 2, 30)
                    continue
                for u in updates:
                    offset = u["update_id"] + 1
                    t = asyncio.create_task(self._safe(u))
                    self.tasks.add(t)
                    t.add_done_callback(self.tasks.discard)
        finally:
            for t in list(self.tasks):
                t.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await self.api.aclose()

    async def _safe(self, u: dict) -> None:
        try:
            if "message" in u:
                await self.on_message(u["message"])
            elif "callback_query" in u:
                await self.on_callback(u["callback_query"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("telegram update failed")

    # ------------------------------------------------------------------ messages
    def _title(self, uid: int) -> str:
        return f"Telegram/{self.name} {uid}"

    def _conversation(self, uid: int) -> str:
        r = self.svc.db.one("SELECT id FROM conversations WHERE title=?", (self._title(uid),))
        return r["id"] if r else self.svc.conversations.create(self._title(uid))["id"]

    async def on_message(self, m: dict) -> None:
        chat, user = m.get("chat") or {}, m.get("from") or {}
        if chat.get("type") != "private" or user.get("is_bot"):
            return
        uid, cid = user.get("id"), chat.get("id")
        if uid not in self.allowed:
            last = self.denied_at.get(uid, 0)
            if time.monotonic() - last > 60:                         # don't let strangers make the bot chatty
                self.denied_at[uid] = time.monotonic()
                await self.api.send(cid, f"Not authorized. Your Telegram user ID is {uid}. If you are the owner, add it "
                                         "to \"Allowed user IDs\" on the Telegram connector in the Atom dashboard.")
            return
        text = (m.get("text") or "").strip()
        if not text:
            await self.api.send(cid, "I can only read text messages for now.")
            return
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd in ("/start", "/help"):
            await self.api.send(cid, HELP)
        elif cmd == "/new":
            r = self.svc.db.one("SELECT id FROM conversations WHERE title=?", (self._title(uid),))
            if r:
                self.svc.conversations.rename(r["id"], f"{self._title(uid)} (until {datetime.now():%Y-%m-%d %H:%M})")
            await self.api.send(cid, "Fresh conversation started.")
        else:
            await self.chat(cid, uid, text)

    async def _typing(self, chat_id: int) -> None:
        while True:
            try:
                await self.api.call("sendChatAction", chat_id=chat_id, action="typing")
            except TelegramError:
                pass
            await asyncio.sleep(4)

    async def chat(self, chat_id: int, uid: int, text: str) -> None:
        async with self.locks.setdefault(chat_id, asyncio.Lock()):           # one turn at a time per chat, in order
            conv = self._conversation(uid)
            typing = asyncio.create_task(self._typing(chat_id))
            final = ""
            try:
                async for ev in self.svc.assistant.converse(conv, text):
                    t = ev["type"]
                    if t == "message_end":
                        final = (ev["message"]["content"] or "").strip() or final
                    elif t == "run_started":
                        await self.api.send(chat_id, f"Started run {ev['run_id']}. Watch it in the dashboard.")
                    elif t == "action_proposed" and ev["action"]["status"] == "pending":
                        a = ev["action"]
                        await self.api.send(chat_id, f"Proposal: {a['summary']}", reply_markup={"inline_keyboard": [[
                            {"text": "Approve", "callback_data": f"a:{a['id']}"},
                            {"text": "Reject", "callback_data": f"r:{a['id']}"}]]})
                    elif t == "error":
                        await self.api.send(chat_id, f"Error: {ev['detail']}")
            finally:
                typing.cancel()
                await asyncio.gather(typing, return_exceptions=True)
            if final:
                await self.api.send(chat_id, final)

    async def on_callback(self, q: dict) -> None:
        user, msg = q.get("from") or {}, q.get("message") or {}
        if user.get("id") not in self.allowed:
            await self.api.call("answerCallbackQuery", callback_query_id=q["id"], text="Not authorized.")
            return
        kind, _, aid = (q.get("data") or "").partition(":")
        try:
            if kind == "a":
                res = await self.svc.executor.approve(aid)
            elif kind == "r":
                res = await self.svc.executor.reject(aid)
            else:
                return
            note = {"approved": "Approved", "rejected": "Rejected"}.get(res["status"], f"Failed: {res.get('result')}")
        except (Conflict, NotFound) as e:
            note = str(e.args[0]) if e.args else "Already decided"
        await self.api.call("answerCallbackQuery", callback_query_id=q["id"], text=note[:190])
        if msg.get("chat"):
            await self.api.call("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                text=f"{(msg.get('text') or '')[:3500]}\n\n{note[:300]}")


class TelegramConnector(Connector):
    type = "telegram"
    label = "Telegram"
    description = "Chat with Atom from a Telegram bot (long polling; nothing is exposed to the internet)."
    background = True
    fields = [
        {"key": "bot_token", "label": "Bot token", "type": "password", "required": True,
         "help": "Talk to @BotFather in Telegram, send /newbot, name it \"Atom\", and paste the token it gives you. "
                 "Kept in the system keychain."},
        {"key": "allowed_user_ids", "label": "Allowed user IDs", "type": "text", "placeholder": "123456789",
         "help": "Comma-separated Telegram user IDs allowed to chat with Atom. Don't know yours? Save this connector "
                 "empty, message the bot once, and it replies with your ID. Nobody else can use the bot."},
        {"key": "allow_agent_send", "label": "Let agents message me", "type": "boolean", "default": True,
         "help": "Adds a telegram_<name>_send tool so scheduled runs can notify you. It only ever writes to the allowed users."},
    ]

    def validate(self, cfg: dict[str, Any]) -> None:
        if not TOKEN_RE.match(cfg.get("bot_token", "")):
            raise Invalid("That doesn't look like a bot token (expected 123456789:ABC...). Get one from @BotFather.")
        parse_ids(cfg.get("allowed_user_ids"))

    async def test(self, cfg: dict[str, Any]) -> str:
        api = BotAPI(cfg["bot_token"])
        try:
            me = await api.call("getMe")
        except TelegramError as e:
            raise ActionError(f"Telegram: {e}") from None
        finally:
            await api.aclose()
        ids = parse_ids(cfg.get("allowed_user_ids"))
        return f"Bot @{me.get('username')} is reachable; " + (
            f"{len(ids)} allowed user(s)." if ids else "no allowed users yet: message the bot to get your ID.")

    async def run(self, name: str, cfg: dict[str, Any], svc: Any) -> None:
        await Bridge(name, cfg, svc, BotAPI(cfg["bot_token"])).run()

    def build_tools(self, name: str, cfg: dict[str, Any]) -> dict[str, ToolSpec]:
        if not cfg.get("bot_token"):
            raise ValueError("no bot token configured")
        ids = parse_ids(cfg.get("allowed_user_ids"))
        if not (cfg.get("allow_agent_send", True) and ids):
            return {}
        tname = f"telegram_{_slug(name)}_send"

        async def send(ctx: ToolContext, a: dict) -> ToolOutput:
            text = str(a["text"]).strip()
            if not text:
                raise ActionError("text is empty.")
            api = BotAPI(cfg["bot_token"])
            try:
                for uid in sorted(ids):
                    await api.send(uid, text)
            except TelegramError as e:
                raise ActionError(f"Telegram error: {e}") from None
            finally:
                await api.aclose()
            return ToolOutput(f"Sent to {len(ids)} Telegram user(s).")

        return {tname: ToolSpec(tname, "Send a Telegram message to the owner (e.g. to report a result or raise an alert). "
                                       "Plain text only. Only send what the user's task asks for.",
                                {"text": {"type": "string"}}, ["text"], send, side_effect=True)}


register(TelegramConnector())

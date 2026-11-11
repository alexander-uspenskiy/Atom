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
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..browser.session import ActionError
from ..stores import Conflict, Invalid, NotFound
from ..tools import ToolContext, ToolOutput, ToolSpec
from . import Connector, register

log = logging.getLogger("atom.telegram")
logging.getLogger("httpx").setLevel(logging.WARNING)       # httpx logs full request URLs at INFO, and the bot token is in the URL

ICON = Path(__file__).parent / "assets" / "atom.png"
SHORT_DESCRIPTION = "Chat with Atom, my local web agent: browse, run tasks, and manage schedules."          # <=120
DESCRIPTION = ("Atom is a personal web agent that runs on my own computer. Ask it to browse the web, check on runs, "
               "set up scheduled tasks and remember things. Private: only the owner can use this bot.")       # <=512

API = "https://api.telegram.org"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024    # the Bot API will not hand over bigger files (getFile limit)
DOC_MIMES = {"application/pdf", "text/markdown", "text/x-markdown", "text/plain", "text/csv", "text/tab-separated-values",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
DOC_EXTS = (".pdf", ".md", ".markdown", ".txt", ".csv", ".tsv", ".docx", ".xlsx")
MAX_CAPTION = 1000
MAX_LEN = 4000                      # Telegram's limit is 4096
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
COMMANDS = [{"command": "new", "description": "Start a fresh conversation"},
            {"command": "help", "description": "What I can do"}]
HELP = ("I'm Atom, your local web agent. Ask me to browse the web, check on runs, or set up schedules. "
        "You can also send me a photo or a document (PDF, Word, Excel, CSV, Markdown, text file) with an optional caption "
        "to read, summarize or answer questions about it.\n\n"
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
        self.token = token
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

    async def download(self, file_id: str, max_bytes: int) -> bytes:
        """Download a file the user sent (getFile + file endpoint)."""
        info = await self.call("getFile", file_id=file_id)
        if (info.get("file_size") or 0) > max_bytes:
            raise TelegramError("file too large")
        try:
            r = await self.client.get(f"{API}/file/bot{self.token}/{info['file_path']}")
        except httpx.HTTPError as e:
            raise TelegramError(f"network error ({type(e).__name__})") from None
        if r.status_code != 200:
            raise TelegramError(f"download failed (HTTP {r.status_code})", r.status_code)
        return r.content

    async def upload(self, method: str, field: str, data: bytes, **params: Any) -> Any:
        """Call a method that takes a file (multipart); `params` are plain form fields."""
        try:
            r = await self.client.post(method, data=params, files={field: ("icon.png", data, "image/png")})
            body = r.json()
        except httpx.HTTPError as e:
            raise TelegramError(f"network error ({type(e).__name__})") from None
        except ValueError:
            raise TelegramError(f"unexpected response (HTTP {r.status_code})", r.status_code) from None
        if not body.get("ok"):
            raise TelegramError(body.get("description") or "request failed", body.get("error_code"))
        return body["result"]

    async def send_photo(self, chat_id: int, data: bytes, caption: str = "", mime: str = "image/jpeg") -> None:
        """Send an image. Captions are limited to 1024 chars by Telegram, so a longer one goes as a text message."""
        ext = {"image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(mime, "jpg")
        cap = caption.strip()
        short = cap if len(cap) <= MAX_CAPTION else ""
        try:
            r = await self.client.post("sendPhoto", data={"chat_id": str(chat_id), **({"caption": short} if short else {})},
                                       files={"photo": (f"image.{ext}", data, mime)})
            body = r.json()
        except httpx.HTTPError as e:
            raise TelegramError(f"network error ({type(e).__name__})") from None
        except ValueError:
            raise TelegramError(f"unexpected response (HTTP {r.status_code})", r.status_code) from None
        if not body.get("ok"):
            raise TelegramError(body.get("description") or "request failed", body.get("error_code"))
        if cap and not short:
            await self.send(chat_id, cap)

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
    async def _notify(self, title: str, text: str) -> None:
        """Sink for finished chat-started runs: forward to the matching Telegram user."""
        for uid in self.allowed:
            if title == self._title(uid):
                await self.api.send(uid, text)

    async def run(self) -> None:
        notifier = getattr(self.svc, "notifier", None)
        if notifier:
            notifier.add_sink(f"telegram:{self.name}", self._notify)
        try:
            await self.api.call("deleteWebhook")                    # getUpdates and webhooks are mutually exclusive
            me = await self.api.call("getMe")
            await self.api.call("setMyCommands", commands=COMMANDS)
            await self._profile(me)
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
            if notifier:
                notifier.remove_sink(f"telegram:{self.name}", self._notify)
            for t in list(self.tasks):
                t.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await self.api.aclose()

    async def _profile(self, me: dict) -> None:
        """Fill in the bot's public profile (descriptions, icon) so it doesn't need setting up in BotFather.
        Best effort and idempotent: only changed values are sent, and failures never stop the bot."""
        try:
            for getter, setter, key, text in (
                    ("getMyDescription", "setMyDescription", "description", DESCRIPTION),
                    ("getMyShortDescription", "setMyShortDescription", "short_description", SHORT_DESCRIPTION)):
                if (await self.api.call(getter)).get(key) != text:
                    await self.api.call(setter, **{key: text})
            if ICON.exists():
                png = ICON.read_bytes()
                marker = self.svc.settings.effective().data_dir / f"telegram-icon-{me.get('id', 0)}.sha"
                digest = hashlib.sha256(png).hexdigest()
                if not marker.exists() or marker.read_text() != digest:
                    await self.api.upload("setMyProfilePhoto", "photo", png,
                                          photo=json.dumps({"type": "static", "photo": "attach://photo"}))
                    marker.write_text(digest)
        except (TelegramError, OSError) as e:
            log.warning("could not update the bot profile: %s", e)

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
        text = (m.get("text") or m.get("caption") or "").strip()
        images: list[str] = []
        file_id, fname = self._file_ref(m)
        if file_id:
            try:
                data = await self.api.download(file_id, MAX_IMAGE_BYTES if m.get("photo") else MAX_FILE_BYTES)
                if fname:
                    await self.api.call("sendChatAction", chat_id=cid, action="typing")
                images = [(await asyncio.to_thread(self.svc.uploads.save, data, fname))["id"]]
            except (TelegramError, Invalid) as e:
                await self.api.send(cid, f"I couldn't use that file: {e.args[0] if e.args else e}")
                return
        if not text and not images:
            await self.api.send(cid, "I can read text messages, photos and documents (PDF, Word, Excel, CSV, Markdown, text).")
            return
        cmd = ""
        if not images:
            cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd in ("/start", "/help"):
            await self.api.send(cid, HELP)
        elif cmd == "/new":
            r = self.svc.db.one("SELECT id FROM conversations WHERE title=?", (self._title(uid),))
            if r:
                self.svc.conversations.rename(r["id"], f"{self._title(uid)} (until {datetime.now():%Y-%m-%d %H:%M})")
            await self.api.send(cid, "Fresh conversation started.")
        else:
            await self.chat(cid, uid, text, images)

    @staticmethod
    def _file_ref(m: dict) -> tuple[str | None, str]:
        """(file_id, file name) of what the message carries: the largest photo size, an image sent as a file ("send
        without compression"), or a supported document. Name is empty for photos."""
        if m.get("photo"):
            best = max(m["photo"], key=lambda p: (p.get("file_size") or 0, p.get("width", 0) * p.get("height", 0)))
            return best["file_id"], ""
        doc = m.get("document") or {}
        mime, name = str(doc.get("mime_type", "")).lower(), str(doc.get("file_name") or "")
        if mime.startswith("image/"):
            return doc.get("file_id"), ""
        if mime in DOC_MIMES or name.lower().endswith(DOC_EXTS):
            return doc.get("file_id"), name or "document"
        return None, ""

    async def _typing(self, chat_id: int) -> None:
        while True:
            try:
                await self.api.call("sendChatAction", chat_id=chat_id, action="typing")
            except TelegramError:
                pass
            await asyncio.sleep(4)

    async def chat(self, chat_id: int, uid: int, text: str, images: list[str] | None = None) -> None:
        async with self.locks.setdefault(chat_id, asyncio.Lock()):           # one turn at a time per chat, in order
            conv = self._conversation(uid)
            typing = asyncio.create_task(self._typing(chat_id))
            final = ""
            try:
                async for ev in self.svc.assistant.converse(conv, text, images=images, can_send_images=True):
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
                    elif t == "image":
                        try:
                            path = Path(ev["path"])
                            mime = "image/png" if path.suffix == ".png" else "image/jpeg"
                            await self.api.send_photo(chat_id, path.read_bytes(), ev.get("caption") or "", mime)
                        except (TelegramError, OSError) as e:
                            await self.api.send(chat_id, f"I couldn't send the image: {e}")
                    elif t == "error":
                        await self.api.send(chat_id, f"Error: {ev['detail']}")
            except (Invalid, NotFound) as e:                  # e.g. no vision projector, unknown upload
                await self.api.send(chat_id, f"Error: {e.args[0] if e.args else e}")
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
        {"key": "forward_user_ids", "label": "Forwarding recipients", "type": "text", "placeholder": "987654321",
         "help": "Comma-separated Telegram user IDs a scheduled job may copy its message to. Nothing is forwarded unless the "
                 "job's instruction says so (e.g. \"forward to 987654321\"); only IDs listed here are accepted. They cannot "
                 "chat with Atom, and each must press Start in the bot once."},
        {"key": "allow_agent_send", "label": "Let agents message me", "type": "boolean", "default": True,
         "help": "Adds a telegram_<name>_send tool so scheduled runs can notify you. It only ever writes to the allowed users."},
    ]

    def validate(self, cfg: dict[str, Any]) -> None:
        if not TOKEN_RE.match(cfg.get("bot_token", "")):
            raise Invalid("That doesn't look like a bot token (expected 123456789:ABC...). Get one from @BotFather.")
        parse_ids(cfg.get("allowed_user_ids"))
        parse_ids(cfg.get("forward_user_ids"))

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
        forwardable = parse_ids(cfg.get("forward_user_ids")) - ids
        tname = f"telegram_{_slug(name)}_send"

        async def send(ctx: ToolContext, a: dict) -> ToolOutput:
            text = str(a["text"]).strip()
            if not text:
                raise ActionError("text is empty.")
            copies: set[int] = set()
            if str(a.get("forward_to") or "").strip():
                want = parse_ids(a["forward_to"])
                bad = want - forwardable - ids
                if bad:
                    raise ActionError(f"forward_to {sorted(bad)} is not in this connector's forwarding recipients "
                                      f"({sorted(forwardable) or 'none configured'}). Nothing was sent.")
                copies = want - ids
            shot = bool(a.get("include_screenshot")) and str(a.get("include_screenshot")).lower() != "false"
            jpg = await ctx.session.look() if shot else None       # fail before sending anything if there is no page
            api = BotAPI(cfg["bot_token"])
            try:
                for uid in sorted(ids):
                    if jpg is not None:
                        await api.send_photo(uid, jpg, text)          # long text goes out as a separate message
                    else:
                        await api.send(uid, text)
                failed = 0
                for uid in sorted(copies):                            # forwarded copies are best effort
                    try:
                        if jpg is not None:
                            await api.send_photo(uid, jpg, text)
                        else:
                            await api.send(uid, text)
                    except TelegramError as e:
                        failed += 1
                        log.warning("telegram forward to %s failed: %s", uid, e)
            except TelegramError as e:
                raise ActionError(f"Telegram error: {e}") from None
            finally:
                await api.aclose()
            extra = f", forwarded to {len(copies) - failed}/{len(copies)}" if copies else ""
            return ToolOutput(f"Sent to {len(ids)} Telegram user(s){extra}" + (" with a screenshot." if jpg is not None else "."))

        return {tname: ToolSpec(tname, "Send a Telegram message to the owner (e.g. to report a result or raise an alert). "
                                       "Plain text; set include_screenshot=true to attach a screenshot of the current page. "
                                       "Set forward_to (comma-separated Telegram user IDs) only when the task tells you to forward "
                                       "the message to someone. Only send what the user's task asks for.",
                                {"text": {"type": "string"}, "include_screenshot": {"type": "boolean"},
                                 "forward_to": {"type": "string"}}, ["text"], send,
                                side_effect=True)}


register(TelegramConnector())

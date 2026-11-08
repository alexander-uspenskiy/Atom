"""Playwright browser session: the only place that touches the browser.

Design rules
- The model never sees raw HTML or screenshots; it gets compact snapshots and paginated text.
- Navigation is policy-checked (domain allowlist, no private-network targets unless explicitly allowed).
- Every run records a Playwright trace (trace.zip) for later replay.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from ..config import Settings
from .reader import extract_readable, paginate
from .snapshot import FIND_JS, SNAPSHOT_JS, Snapshot, build_snapshot, format_snapshot


class ActionError(Exception):
    """A browser action failed in a way the model can act on. The message is shown to the model."""


def _is_private_host(host: str) -> bool:
    h = host.strip("[]").lower()
    if h in ("localhost", "") or h.endswith(".localhost") or h.endswith(".local") or h.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


@dataclass
class Policy:
    allowed_domains: list[str] | None = None      # None = any public host
    allow_private: bool = False                   # allow localhost / LAN targets (tests, dev)
    blocked_log: list[str] = field(default_factory=list)

    def _domain_ok(self, host: str) -> bool:
        if self.allowed_domains is None:
            return True
        host = host.lower().strip("[]")
        return any(host == d or host.endswith("." + d) for d in (x.lower() for x in self.allowed_domains))

    def check_url(self, url: str, *, navigation: bool) -> str | None:
        """Return None if allowed, else a reason string."""
        p = urlparse(url)
        if p.scheme in ("data", "blob", "about"):
            return None if p.scheme != "data" or not navigation else "data: navigation not allowed"
        if p.scheme not in ("http", "https"):
            return f"scheme '{p.scheme}' not allowed"
        host = p.hostname or ""
        explicit = self.allowed_domains is not None and self._domain_ok(host)
        if _is_private_host(host) and not (self.allow_private or explicit):
            return f"private/local address '{host}' not allowed"
        if navigation and not self._domain_ok(host):
            return f"domain '{host}' not in allowlist {self.allowed_domains}"
        return None


# Resolves once the DOM has had no mutations for `quiet` ms (or after `max` ms). Args: [quiet, max].
STABLE_JS = """([quiet, max]) => new Promise(resolve => {
  let timer; const t0 = Date.now();
  const done = () => { obs.disconnect(); resolve(true); };
  const arm = () => { clearTimeout(timer); timer = setTimeout(done, Math.max(0, Math.min(quiet, max - (Date.now() - t0)))); };
  const obs = new MutationObserver(arm);
  obs.observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true});
  arm(); setTimeout(done, max);
})"""
LOOK_MAX_HEIGHT = 3000      # px; taller pages are cut off (the model downsamples big images anyway)


class BrowserSession:
    def __init__(self, settings: Settings, policy: Policy | None = None, run_dir: Path | None = None,
                 profile: Path | None = None, load_images: bool = False):
        self.s = settings
        self.load_images = load_images      # let page images load (needed for useful screenshots)
        self.policy = policy or Policy()
        self.run_dir = run_dir
        self.profile = profile
        self._pw: Playwright | None = None
        self._browser = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None
        self._last_snap: Snapshot | None = None
        self._text_cache: tuple[tuple[str, int], str, str] | None = None
        self.notes: list[str] = []          # one-shot messages (dialogs, new tabs) shown with next observation
        self.visited: list[str] = []
        self.requested_hosts: set[str] = set()

    # ---------- lifecycle ----------
    async def start(self) -> None:
        self._pw = await async_playwright().start()
        viewport = {"width": 1280, "height": 900}
        if self.profile:
            self.profile.mkdir(parents=True, exist_ok=True)
            self.ctx = await self._pw.chromium.launch_persistent_context(
                str(self.profile), headless=self.s.headless, viewport=viewport, accept_downloads=False)
        else:
            self._browser = await self._pw.chromium.launch(headless=self.s.headless)
            self.ctx = await self._browser.new_context(viewport=viewport, accept_downloads=False)
        self.ctx.set_default_timeout(self.s.action_timeout_ms)
        self.ctx.set_default_navigation_timeout(self.s.nav_timeout_ms)
        await self.ctx.route("**/*", self._route)
        self.ctx.on("page", self._on_new_page)
        if self.run_dir:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            await self.ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        self._hook_page(self.page)

    async def close(self) -> None:
        try:
            if self.ctx and self.run_dir:
                await self.ctx.tracing.stop(path=str(self.run_dir / "trace.zip"))
        except Exception:  # noqa: BLE001
            pass
        for closer in (self.ctx, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw:
            await self._pw.stop()

    # ---------- hooks ----------
    async def _route(self, route) -> None:
        req = route.request
        try:
            host = urlparse(req.url).hostname or ""
            if host:
                self.requested_hosts.add(host)
            if req.resource_type in self.s.block_resources and not (self.load_images and req.resource_type == "image"):
                return await route.abort()
            nav = req.is_navigation_request() and req.frame == self.page.main_frame if self.page else False
            reason = self.policy.check_url(req.url, navigation=nav)
            if reason:
                self.policy.blocked_log.append(f"{req.url} ({reason})")
                return await route.abort()
            await route.continue_()
        except Exception:  # noqa: BLE001
            try:
                await route.abort()
            except Exception:  # noqa: BLE001
                pass

    def _hook_page(self, page: Page) -> None:
        async def on_dialog(d):
            self.notes.append(f"A {d.type} dialog appeared and was dismissed: \"{d.message[:160]}\"")
            try:
                await (d.accept() if d.type == "alert" else d.dismiss())
            except Exception:  # noqa: BLE001
                pass
        page.on("dialog", lambda d: asyncio.ensure_future(on_dialog(d)))
        page.on("framenavigated", lambda f: self.visited.append(f.url) if f == page.main_frame else None)

    def _on_new_page(self, page: Page) -> None:
        self._hook_page(page)

    # ---------- helpers ----------
    def _need_page(self) -> Page:
        if not self.page:
            raise ActionError("browser not started")
        return self.page

    async def _settle(self) -> None:
        page = self._need_page()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            await page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:  # noqa: BLE001
            pass

    async def _wait_stable(self, quiet_ms: int = 350, max_ms: int = 2500) -> None:
        """Wait until the DOM stops mutating. Single-page apps re-render a moment after a click; reading text or
        taking a snapshot before that returns the PREVIOUS view, which small models then misread as a broken page."""
        try:
            await self._need_page().evaluate(STABLE_JS, [quiet_ms, max_ms])
        except Exception:  # noqa: BLE001
            pass

    def _locator(self, ref: str):
        ref = ref.strip().strip("[]")
        if not re.fullmatch(r"e\d+", ref):
            raise ActionError(f"'{ref}' is not a valid ref (expected like e12). Use refs from the latest snapshot.")
        return self._need_page().locator(f'[data-atom-ref="{ref}"]').first

    async def _require(self, ref: str):
        loc = self._locator(ref)
        if await loc.count() == 0:
            raise ActionError(f"Ref {ref} not found: the page has changed. Call snapshot to get fresh refs.")
        return loc

    async def _after_action(self, before_url: str, pages_before: int) -> str:
        await asyncio.sleep(0.25)
        msgs = []
        if self.ctx and len(self.ctx.pages) > pages_before:
            self.page = self.ctx.pages[-1]
            self._last_snap = None
            msgs.append("A new tab opened; now viewing it.")
        await self._settle()
        await self._wait_stable()
        if self._need_page().url != before_url:
            msgs.append(f"Navigated to {self.page.url}")
            self._last_snap = None
        return " ".join(msgs)

    # ---------- actions ----------
    async def goto(self, url: str) -> str:
        url = url.strip()
        if not re.match(r"^[a-z][a-z0-9+.-]*:", url):
            url = "https://" + url
        reason = self.policy.check_url(url, navigation=True)
        if reason:
            self.policy.blocked_log.append(f"{url} ({reason})")
            raise ActionError(f"Navigation blocked by policy: {reason}")
        page = self._need_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            if "ERR_ABORTED" in str(e) or "net::ERR" in str(e):
                blocked = [b for b in self.policy.blocked_log if url in b]
                raise ActionError(f"Navigation failed: {blocked[-1] if blocked else str(e).splitlines()[0]}")
            raise ActionError(f"Navigation failed: {str(e).splitlines()[0]}")
        await self._settle()
        self._last_snap = None
        status = resp.status if resp else "?"
        if page.url != url and self.policy.blocked_log and any(page.url in b for b in self.policy.blocked_log[-3:]):
            raise ActionError("Redirect blocked by policy")
        return f"Opened {page.url} (HTTP {status})"

    async def click(self, ref: str) -> str:
        loc = await self._require(ref)
        page = self._need_page()
        before_url, n_pages = page.url, len(self.ctx.pages)
        try:
            await loc.click()
        except Exception as e:  # noqa: BLE001
            raise ActionError(f"Click on {ref} failed: {str(e).splitlines()[0][:200]}")
        extra = await self._after_action(before_url, n_pages)
        return f"Clicked {ref}. {extra}".strip()

    async def fill(self, ref: str, text: str, submit: bool = False) -> str:
        loc = await self._require(ref)
        page = self._need_page()
        before_url, n_pages = page.url, len(self.ctx.pages)
        try:
            await loc.fill(text)
            if submit:
                await loc.press("Enter")
        except Exception as e:  # noqa: BLE001
            raise ActionError(f"Typing into {ref} failed: {str(e).splitlines()[0][:200]}")
        extra = await self._after_action(before_url, n_pages) if submit else ""
        return f"Typed into {ref}{' and pressed Enter' if submit else ''}. {extra}".strip()

    async def select(self, ref: str, value: str) -> str:
        loc = await self._require(ref)
        try:
            try:
                await loc.select_option(label=value, timeout=2000)
            except Exception:  # noqa: BLE001
                await loc.select_option(value=value, timeout=2000)
        except Exception as e:  # noqa: BLE001
            raise ActionError(f"Selecting '{value}' in {ref} failed: {str(e).splitlines()[0][:200]}")
        return f"Selected '{value}' in {ref}."

    async def press(self, key: str) -> str:
        page = self._need_page()
        before_url, n_pages = page.url, len(self.ctx.pages)
        try:
            await page.keyboard.press(key)
        except Exception as e:  # noqa: BLE001
            raise ActionError(f"Key press '{key}' failed: {str(e).splitlines()[0][:200]}")
        extra = await self._after_action(before_url, n_pages)
        return f"Pressed {key}. {extra}".strip()

    async def scroll(self, direction: str = "down") -> str:
        page = self._need_page()
        js = {"down": "window.scrollBy(0, window.innerHeight * 0.8)", "up": "window.scrollBy(0, -window.innerHeight * 0.8)",
              "top": "window.scrollTo(0, 0)", "bottom": "window.scrollTo(0, document.documentElement.scrollHeight)"}
        if direction not in js:
            raise ActionError("direction must be one of: down, up, top, bottom")
        await page.evaluate(js[direction])
        await asyncio.sleep(0.2)
        return f"Scrolled {direction}."

    async def back(self) -> str:
        page = self._need_page()
        before = page.url
        await page.go_back(wait_until="domcontentloaded")
        await self._settle()
        self._last_snap = None
        return f"Went back to {page.url}" if page.url != before else "No previous page."

    async def wait(self, ms: int = 1000, text: str | None = None) -> str:
        page = self._need_page()
        if text:
            try:
                await page.get_by_text(text).first.wait_for(timeout=min(ms, 15000))
                return f"Text '{text}' appeared."
            except Exception:  # noqa: BLE001
                return f"Text '{text}' did not appear within {min(ms, 15000)} ms."
        await asyncio.sleep(min(ms, 15000) / 1000)
        return f"Waited {min(ms, 15000)} ms."

    # ---------- observations ----------
    async def snapshot(self, diff: bool = False) -> str:
        page = self._need_page()
        raw = await page.evaluate(SNAPSHOT_JS, 60)
        snap = build_snapshot(raw, max_elements=80)
        snap.notes = self.notes[:]
        self.notes.clear()
        prev = self._last_snap if diff else None
        text = format_snapshot(snap, prev)
        self._last_snap = snap
        return text

    async def read_text(self, offset: int = 0, mode: str = "auto") -> str:
        page = self._need_page()
        await self._wait_stable(250, 1500)
        inner = await page.evaluate("document.body ? document.body.innerText : ''")
        key = (page.url, hash(inner))
        if self._text_cache and self._text_cache[0] == key and self._text_cache[2] == mode:
            text = self._text_cache[1]
        else:
            html = "" if mode == "full" else await page.content()
            text, _ = extract_readable(html, inner, mode, page.url)
            self._text_cache = (key, text, mode)
        chunk, nxt, total = paginate(text, max(0, offset), self.s.max_read_tokens)
        if not chunk:
            return f"(no more text; page has {total} characters)"
        tail = f"\n[showing characters {offset}-{offset + len(chunk)} of {total}; " + \
               (f"call read_text(offset={nxt}) for more]" if nxt != -1 else "end of page]")
        return chunk + tail

    async def page_text_for_extract(self, offset: int = 0) -> tuple[str, int]:
        """Raw chunk for the extraction call. Returns (chunk, next_offset or -1)."""
        page = self._need_page()
        await self._wait_stable(250, 1500)
        html = await page.content()
        inner = await page.evaluate("document.body ? document.body.innerText : ''")
        text, _ = extract_readable(html, inner, "auto", page.url)
        chunk, nxt, _ = paginate(text, max(0, offset), self.s.max_extract_tokens)
        return chunk, nxt

    async def find(self, query: str) -> str:
        page = self._need_page()
        hits = await page.evaluate(FIND_JS, query)
        if not hits:
            return f"No visible text matching '{query}'."
        lines = []
        for h in hits:
            where = f"  -> [{h['ref']}] {h['tag']}" if h.get("ref") else ""
            lines.append(f"- \"{h['text']}\"{where}")
        return f"Matches for '{query}':\n" + "\n".join(lines)

    async def screenshot(self, name: str = "shot.png") -> Path | None:
        if not self.run_dir:
            return None
        path = self.run_dir / name
        await self._need_page().screenshot(path=str(path))
        return path

    async def look(self, full_page: bool = False) -> bytes:
        """JPEG of the visible viewport (or the whole page, capped at LOOK_MAX_HEIGHT px) for the model to look at."""
        page = self._need_page()
        if not full_page:
            return await page.screenshot(type="jpeg", quality=75, timeout=10000)
        size = await page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
        w, h = int(size[0]), int(size[1])
        return await page.screenshot(type="jpeg", quality=75, timeout=15000, full_page=True,
                                     clip={"x": 0, "y": 0, "width": max(1, w), "height": max(1, min(h, LOOK_MAX_HEIGHT))})

    async def shot(self, n: int) -> tuple[Path, str] | None:
        """Small JPEG of the current page for the live dashboard view. Returns (path, title)."""
        if not self.run_dir or not self.page:
            return None
        shots = self.run_dir / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        path = shots / f"{n}.jpg"
        await self.page.screenshot(path=str(path), type="jpeg", quality=55, timeout=5000)
        try:
            title = await self.page.title()
        except Exception:  # noqa: BLE001
            title = ""
        return path, title

    @property
    def url(self) -> str:
        return self.page.url if self.page else ""

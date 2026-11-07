"""Deterministic tests for the browser layer (no LLM needed)."""
from __future__ import annotations

import pytest

from atom.browser import BrowserSession, Policy
from atom.browser.reader import paginate
from atom.browser.session import ActionError
from atom.config import Settings
from evals.fixtures.server import FixtureServer

@pytest.fixture(scope="module")
def site():
    srv = FixtureServer().start()
    yield srv
    srv.stop()


@pytest.fixture
async def sess(site):
    s = BrowserSession(Settings(), Policy(allow_private=True))
    await s.start()
    yield s
    await s.close()


async def test_snapshot_lists_refs_and_diffs(sess, site):
    await sess.goto(f"{site.base}/login")
    snap = await sess.snapshot()
    assert 'textbox "Username"' in snap and "password" in snap and 'button "Sign in"' in snap
    ref = next(l.split("]")[0][1:] for l in snap.splitlines() if 'textbox "Username"' in l)
    await sess.fill(ref, "dana")
    diff = await sess.snapshot(diff=True)
    assert "showing changes" in diff and 'value="dana"' in diff


def _ref(snap: str, needle: str) -> str:
    return next(l.split("]")[0][1:] for l in snap.splitlines() if l.startswith("[e") and needle in l)


async def test_login_error_text_is_readable(sess, site):
    await sess.goto(f"{site.base}/login")
    snap = await sess.snapshot()
    await sess.fill(_ref(snap, "Username"), "dana")
    await sess.fill(_ref(snap, "Password"), "wrong")
    await sess.click(_ref(snap, "Sign in"))
    assert "Invalid username or password" in await sess.read_text()


async def test_policy_blocks_private_and_off_allowlist(site):
    s = BrowserSession(Settings(), Policy(allow_private=False))
    await s.start()
    try:
        with pytest.raises(ActionError, match="private"):
            await s.goto(f"{site.base}/")
        with pytest.raises(ActionError, match="scheme"):
            await s.goto("file:///etc/passwd")
    finally:
        await s.close()
    s = BrowserSession(Settings(), Policy(allowed_domains=["127.0.0.1"]))
    await s.start()
    try:
        await s.goto(f"{site.base}/")          # explicit allowlist entry permits the private host
        with pytest.raises(ActionError, match="allowlist"):
            await s.goto("https://example.org/")
    finally:
        await s.close()


async def test_stale_ref_gives_actionable_error(sess, site):
    await sess.goto(f"{site.base}/")
    with pytest.raises(ActionError, match="not found"):
        await sess.click("e999")
    with pytest.raises(ActionError, match="not a valid ref"):
        await sess.click("login-button")


async def test_read_text_paginates(sess, site):
    await sess.goto(f"{site.base}/staff")
    sess.s.max_read_tokens = 40
    first = await sess.read_text()
    assert "call read_text(offset=" in first
    nxt = int(first.split("offset=")[1].split(")")[0])
    second = await sess.read_text(offset=nxt)
    assert second != first


def test_paginate_cuts_on_line_boundary():
    text = "\n".join(f"line {i}" for i in range(200))
    chunk, nxt, total = paginate(text, 0, 50)
    assert nxt > 0 and text[nxt - 1] != "\n" and chunk.endswith(tuple("0123456789"))
    assert total == len(text)

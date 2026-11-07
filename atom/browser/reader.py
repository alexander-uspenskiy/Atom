"""Page text extraction (readable markdown) with pagination so the model reads in small, cheap chunks."""
from __future__ import annotations

import re

import trafilatura

CHARS_PER_TOKEN = 3.6


def est_tokens(s: str) -> int:
    return int(len(s) / CHARS_PER_TOKEN) + 1


def _clean(s: str) -> str:
    s = re.sub(r"[ \t ]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_readable(html: str, inner_text: str, mode: str = "auto", url: str | None = None) -> tuple[str, str]:
    """Return (text, method). mode: auto | article | full."""
    full = _clean(inner_text or "")
    if mode == "full":
        return full, "innerText"
    article = trafilatura.extract(html, url=url, output_format="markdown", include_tables=True,
                                  include_links=False, include_comments=False, favor_recall=True) or ""
    article = _clean(article)
    if mode == "article":
        return (article or full), ("trafilatura" if article else "innerText")
    # auto: trafilatura drops lists/tables on non-article pages; fall back when it removed too much
    if article and (len(article) >= 0.5 * len(full) or len(full) > 60000):
        return article, "trafilatura"
    return full, "innerText"


def paginate(text: str, offset: int, max_tokens: int) -> tuple[str, int, int]:
    """Return (chunk, next_offset or -1, total_chars). Cuts on a line boundary where possible."""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    total = len(text)
    if offset >= total:
        return "", -1, total
    end = min(total, offset + max_chars)
    if end < total:
        nl = text.rfind("\n", offset + int(max_chars * 0.6), end)
        if nl != -1:
            end = nl
    chunk = text[offset:end]
    return chunk, (end if end < total else -1), total

"""Compact page snapshots: interactive elements with stable refs, not raw HTML.

Refs are stored on the elements themselves (data-atom-ref) so they stay stable between snapshots of the
same page. A new snapshot after an action is returned as a diff when the URL did not change, which keeps
each agent step small (prefill on this hardware is ~100 tok/s, so tokens are expensive).

Known limit (Phase 1): iframes and shadow DOM are not traversed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SNAPSHOT_JS = r"""
(maxNameLen) => {
  const w = window;
  w.__atomN = w.__atomN || 0;
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], ' +
    '[role=tab], [role=menuitem], [role=checkbox], [role=radio], [role=switch], [role=option], [role=combobox], ' +
    '[role=textbox], [role=searchbox], [contenteditable=""], [contenteditable=true], [onclick], ' +
    '[tabindex]:not([tabindex="-1"])';
  const txt = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) return false;
    if (el.closest('[aria-hidden="true"], [inert]')) return false;
    return true;
  };
  const nameOf = (el) => {
    let n = el.getAttribute('aria-label');
    if (!n) {
      const ids = el.getAttribute('aria-labelledby');
      if (ids) n = ids.split(/\s+/).map(i => { const e = document.getElementById(i); return e ? (e.innerText || e.textContent) : ''; }).join(' ');
    }
    if (!n && el.labels && el.labels.length) n = Array.from(el.labels).map(l => l.innerText).join(' ');
    if (!n && el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type)) n = el.value;
    if (!n) n = el.innerText || el.textContent;
    if (!txt(n)) { const img = el.querySelector('img[alt]'); if (img) n = img.alt; }
    if (!txt(n)) n = el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || el.getAttribute('alt');
    return txt(n).slice(0, maxNameLen);
  };
  const roleOf = (el) => {
    const r = el.getAttribute('role');
    if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a') return 'link';
    if (t === 'button' || t === 'summary') return 'button';
    if (t === 'select') return 'combobox';
    if (t === 'textarea') return 'textbox';
    if (t === 'input') {
      const ty = (el.type || 'text').toLowerCase();
      if (['submit', 'button', 'reset', 'image'].includes(ty)) return 'button';
      if (ty === 'checkbox') return 'checkbox';
      if (ty === 'radio') return 'radio';
      if (ty === 'search') return 'searchbox';
      if (ty === 'password') return 'password';
      return 'textbox';
    }
    return 'clickable';
  };
  const els = [];
  const seen = new Set();
  document.querySelectorAll(SEL).forEach((el) => {
    if (seen.has(el) || !vis(el)) return;
    seen.add(el);
    if (!el.dataset.atomRef) el.dataset.atomRef = 'e' + (++w.__atomN);
    const role = roleOf(el);
    const o = { ref: el.dataset.atomRef, role, name: nameOf(el), y: Math.round(el.getBoundingClientRect().top + w.scrollY) };
    if (role === 'link') { const h = el.getAttribute('href') || ''; if (h && !h.startsWith('javascript:')) o.href = h.slice(0, 90); }
    if (['textbox', 'searchbox', 'password', 'combobox'].includes(role) && 'value' in el) {
      o.value = role === 'password' ? (el.value ? '•••' : '') : (el.value || '').slice(0, 60);
    }
    if (el.tagName === 'SELECT') {
      o.value = el.selectedOptions[0] ? txt(el.selectedOptions[0].text) : '';
      o.options = Array.from(el.options).slice(0, 12).map(x => txt(x.text));
    }
    if (role === 'checkbox' || role === 'radio' || role === 'switch') o.checked = !!el.checked || el.getAttribute('aria-checked') === 'true';
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') o.disabled = true;
    if (el.required) o.required = true;
    els.push(o);
  });
  const headings = Array.from(document.querySelectorAll('h1, h2')).filter(vis).slice(0, 6).map(h => txt(h.innerText).slice(0, 80)).filter(Boolean);
  const alerts = Array.from(document.querySelectorAll('[role=alert], [role=dialog], [aria-live=assertive], .error, .alert')).filter(vis).slice(0, 3).map(a => txt(a.innerText).slice(0, 160)).filter(Boolean);
  const de = document.documentElement;
  const text = (document.body ? document.body.innerText : '').slice(0, 30000);
  return { url: location.href, title: document.title, scrollY: Math.round(w.scrollY), scrollH: de.scrollHeight,
           vh: w.innerHeight, headings, alerts, elements: els, text };
}
"""

FIND_JS = r"""
(query) => {
  const q = query.toLowerCase();
  const w = window;
  w.__atomN = w.__atomN || 0;
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], [onclick]';
  const txt = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  const refOf = (el) => { if (!el.dataset.atomRef) el.dataset.atomRef = 'e' + (++w.__atomN); return el.dataset.atomRef; };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode()) && out.length < 12) {
    const t = node.nodeValue;
    const i = t.toLowerCase().indexOf(q);
    if (i < 0) continue;
    const el = node.parentElement;
    if (!el || el.closest('script, style, noscript')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const inter = el.closest(SEL);
    const ctx = txt((el.closest('li, tr, p, div') || el).innerText).slice(0, 140);
    out.push({ text: ctx, ref: inter ? refOf(inter) : null, tag: inter ? inter.tagName.toLowerCase() : null });
  }
  return out;
}
"""


@dataclass
class Snapshot:
    url: str
    title: str
    scroll_pct: int
    headings: list[str]
    alerts: list[str]
    lines: dict[str, str]          # ref -> rendered line (insertion ordered)
    truncated: int = 0
    total: int = 0
    notes: list[str] = field(default_factory=list)
    text_lines: list[str] = field(default_factory=list)   # visible text lines, used only for diffs


def render_line(e: dict) -> str:
    parts = [f"[{e['ref']}] {e['role']}"]
    if e.get("name"):
        parts.append(f"\"{e['name']}\"")
    if "value" in e and e["value"] != "":
        parts.append(f"value=\"{e['value']}\"")
    if e.get("options"):
        parts.append("options=[" + " | ".join(e["options"]) + "]")
    if e.get("checked") is not None:
        parts.append("checked" if e["checked"] else "unchecked")
    if e.get("disabled"):
        parts.append("(disabled)")
    if e.get("required"):
        parts.append("(required)")
    if e.get("href"):
        parts.append(f"-> {e['href']}")
    return " ".join(parts)


def build_snapshot(raw: dict, max_elements: int) -> Snapshot:
    els = raw["elements"]
    total = len(els)
    vh, sy = raw["vh"], raw["scrollY"]
    if total > max_elements:
        # keep elements near the viewport first, then fill in DOM order
        near = [i for i, e in enumerate(els) if sy - 0.25 * vh <= e["y"] <= sy + 1.5 * vh]
        keep = set(near[:max_elements])
        for i in range(total):
            if len(keep) >= max_elements:
                break
            keep.add(i)
        els = [e for i, e in enumerate(els) if i in keep]
    lines = {e["ref"]: render_line(e) for e in els}
    denom = max(1, raw["scrollH"] - vh)
    return Snapshot(url=raw["url"], title=raw["title"], scroll_pct=min(100, round(100 * sy / denom)),
                    headings=raw["headings"], alerts=raw["alerts"], lines=lines,
                    truncated=total - len(els), total=total,
                    text_lines=[t.strip() for t in raw.get("text", "").split("\n") if t.strip()])


def format_snapshot(snap: Snapshot, prev: Snapshot | None = None) -> str:
    head = [f"URL: {snap.url}", f"Title: {snap.title}", f"Scroll: {snap.scroll_pct}%"]
    if snap.headings:
        head.append("Headings: " + " | ".join(snap.headings))
    if snap.alerts:
        head.append("Alerts: " + " || ".join(snap.alerts))
    head.extend(snap.notes)
    if prev is not None and prev.url == snap.url:
        added = [l for r, l in snap.lines.items() if r not in prev.lines]
        changed = [l for r, l in snap.lines.items() if r in prev.lines and prev.lines[r] != l]
        removed = [r for r in prev.lines if r not in snap.lines]
        body = ["(same page; showing changes since last snapshot)"]
        if added:
            body.append("New elements:")
            body.extend(added)
        if changed:
            body.append("Changed elements:")
            body.extend(changed)
        if removed:
            body.append("Removed refs: " + ", ".join(removed[:30]) + (" ..." if len(removed) > 30 else ""))
        old_text = set(prev.text_lines)
        new_text = [t[:160] for t in snap.text_lines if t not in old_text][:6]
        if new_text:
            body.append("New page text:")
            body.extend(f"  {t}" for t in new_text)
        if not (added or changed or removed or new_text):
            body.append("Nothing visibly changed.")
        if snap.truncated:
            body.append(f"({snap.truncated} more elements hidden; use find or snapshot)")
        return "\n".join(head + body)
    body = ["Interactive elements:"] + list(snap.lines.values())
    if snap.truncated:
        body.append(f"... {snap.truncated} more elements not shown (of {snap.total}); "
                    "use find(query), scroll, or read_text to see more.")
    if not snap.lines:
        body = ["No interactive elements visible. Use read_text to read the page."]
    return "\n".join(head + body)

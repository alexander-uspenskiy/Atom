"""The done tool pushes back once on implausible scale weights (ghost LCD digits glued to the real reading)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from atom.tools import implausible_scale_weight, t_done

SCALE = 'display: bright digits 1,8,0,0,0; faint ghost "-18" ignored; unit g => 1800 g'


def meal(grams):
    return json.dumps({"is_food": True, "items": [{"name": "stuffed mushrooms", "grams": grams}]})


def test_flags_big_scale_item():
    assert "1800" in implausible_scale_weight(SCALE, meal(1800))


def test_accepts_normal_weight_and_no_scale_and_non_meal():
    assert implausible_scale_weight(SCALE, meal(119)) is None
    assert implausible_scale_weight("display: none visible", meal(1800)) is None
    assert implausible_scale_weight(SCALE, "plain text") is None
    assert implausible_scale_weight(SCALE, json.dumps({"items": [{"name": "x", "grams": "n/a"}]})) is None


def test_done_rejects_once_then_accepts():
    ctx = SimpleNamespace(counters={})
    args = {"evidence": SCALE, "result": meal(1800)}
    first = asyncio.run(t_done(ctx, args))
    assert not first.terminal and not first.ok and "ghost" in first.text
    second = asyncio.run(t_done(ctx, args))
    assert second.terminal and second.result == args["result"]


def test_done_passes_corrected_reading():
    ctx = SimpleNamespace(counters={})
    out = asyncio.run(t_done(ctx, {"evidence": SCALE, "result": meal(119)}))
    assert out.terminal

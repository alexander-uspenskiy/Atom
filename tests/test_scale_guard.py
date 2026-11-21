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


# ---------------------------------------------------------------- zoom_image
def _jpeg(w=400, h=300):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


def test_zoom_crop_enlarges_region():
    import io
    from PIL import Image
    from atom.tools import ZOOM_TARGET_PX, zoom_crop
    out = Image.open(io.BytesIO(zoom_crop(_jpeg(), 0.25, 0.5, 0.75, 0.9)))
    assert max(out.size) == ZOOM_TARGET_PX and abs(out.width / out.height - (200 / 120)) < 0.02


def test_zoom_crop_rejects_tiny_region():
    import pytest
    from atom.browser.session import ActionError
    from atom.tools import zoom_crop
    with pytest.raises(ActionError):
        zoom_crop(_jpeg(), 0.5, 0.5, 0.501, 0.501)


def test_zoom_tool_validates_and_returns_image(tmp_path):
    import pytest
    from atom.browser.session import ActionError
    from atom.tools import t_zoom_image
    from atom.uploads import UploadStore
    store = UploadStore(tmp_path)
    uid = store.save(_jpeg(), "a.jpg")["id"]
    ctx = SimpleNamespace(uploads=store, images=[uid], counters={})
    out = asyncio.run(t_zoom_image(ctx, {"image": 1, "x0": 0.2, "y0": 0.2, "x1": 0.8, "y1": 0.8}))
    assert out.images and out.images[0].startswith("data:image/jpeg;base64,")
    for bad in ({"image": 2, "x0": 0, "y0": 0, "x1": 1, "y1": 1}, {"x0": 0.8, "y0": 0, "x1": 0.2, "y1": 1},
                {"x0": 0, "y0": 0, "x1": 2, "y1": 1}):
        with pytest.raises(ActionError):
            asyncio.run(t_zoom_image(ctx, bad))
    with pytest.raises(ActionError):
        asyncio.run(t_zoom_image(SimpleNamespace(uploads=None, images=[], counters={}), {"x0": 0, "y0": 0, "x1": 1, "y1": 1}))

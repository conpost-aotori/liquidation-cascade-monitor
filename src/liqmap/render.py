"""Turn a :class:`LiquidationMap` into a PNG via HTML/CSS + headless Chromium.

The chart is pure HTML/CSS (no JS charting lib): each band is an absolutely
positioned bar inside a relative plot region. All layout math (price -> y%,
notional -> width%, notional -> colour intensity) happens here so the Jinja
template stays declarative.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .bias import FIRE_SCORE
from .models import LiquidationMap

WIDTH = 1600
HEIGHT = 900

_TEMPLATES = Path(__file__).parent / "templates"

# Bar colours: muted (small clusters) -> vivid (the big walls).
_LONG_MUTED = (0x59, 0x23, 0x33)
_LONG_VIVID = (0xFF, 0x4D, 0x6D)
_SHORT_MUTED = (0x1C, 0x5D, 0x49)
_SHORT_VIVID = (0x33, 0xE0, 0x9B)


# ----- formatting ----------------------------------------------------------
def fmt_price(x: float) -> str:
    return f"${x:,.0f}"


def fmt_notional(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:.2f}B"
    return f"${x / 1e6:.0f}M"


# ----- colour --------------------------------------------------------------
def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _mix(c1, c2, t: float) -> tuple[int, int, int]:
    return (_lerp(c1[0], c2[0], t), _lerp(c1[1], c2[1], t), _lerp(c1[2], c2[2], t))


def _bar_colors(side: str, intensity: float) -> tuple[str, str]:
    """Return (main, darker-edge) hex for a bar, scaled by intensity 0..1."""
    muted, vivid = (_LONG_MUTED, _LONG_VIVID) if side == "long" else (_SHORT_MUTED, _SHORT_VIVID)
    t = 0.30 + 0.70 * max(0.0, min(1.0, intensity))
    main = _mix(muted, vivid, t)
    dark = _mix(main, (0, 0, 0), 0.30)  # left edge for a subtle sheen
    return _hex(main), _hex(dark)


def _nice_axis_max(raw: float) -> float:
    """Smallest 'nice' value >= raw*1.05 that divides into 4 clean ticks."""
    if raw <= 0:
        return 1.0
    target = raw * 1.05 / 4
    mag = 10 ** math.floor(math.log10(target))
    for mult in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        step = mult * mag
        if step >= target:
            return step * 4
    return target * 4


# ----- layout --------------------------------------------------------------
def build_context(m: LiquidationMap) -> dict:
    step = m.band_step
    domain_top = m.price_max + step / 2
    domain_bottom = m.price_min - step / 2
    span = domain_top - domain_bottom

    def y_pct(price: float) -> float:
        return round((domain_top - price) / span * 100, 3)

    slot_pct = step / span * 100
    bar_h = round(slot_pct * 0.70, 3)  # leave gaps between bars

    axis_max = _nice_axis_max(m.max_notional)

    def w_pct(notional: float) -> float:
        return round(notional / axis_max * 100, 3)

    key_by_price = {kl.price: kl for kl in m.key_levels}

    # Only annotate key levels that are vertically spaced, to avoid crowding
    # (e.g. adjacent 72k/71k). The side panel still lists every key level.
    annotate_prices: set[float] = set()
    for kl in sorted(m.key_levels, key=lambda k: -k.notional):
        if all(abs(kl.price - p) > m.band_step * 1.5 for p in annotate_prices):
            annotate_prices.add(kl.price)

    bands = []
    for b in m.bands:
        side = b.dominant_side
        intensity = b.notional / m.max_notional if m.max_notional else 0.0
        main, dark = _bar_colors(side, intensity)
        kl = key_by_price.get(b.price)
        width = w_pct(b.notional)
        # Wide bars carry their value inside; only notable shorter non-key bars label outside.
        value_inside = width >= 16 and b.notional > 0
        value_outside = (
            not value_inside and kl is None and m.max_notional > 0 and b.notional >= 0.18 * m.max_notional
        )
        bands.append(
            {
                "side": side,
                "center": y_pct(b.price),
                "top": round(y_pct(b.price) - bar_h / 2, 3),
                "height": bar_h,
                "width": width,
                "color": main,
                "color_dark": dark,
                "annotation": kl.label if (kl and b.price in annotate_prices) else None,
                "ann_side": side,
                "value": fmt_notional(b.notional),
                "value_inside": value_inside,
                "value_outside": value_outside,
            }
        )

    # price-axis labels every $1,000
    lo = int(math.ceil(m.price_min / 1000.0) * 1000)
    hi = int(math.floor(m.price_max / 1000.0) * 1000)
    y_labels = [
        {"label": fmt_price(p), "top": y_pct(p)} for p in range(lo, hi + 1, 1000)
    ]

    x_ticks = [
        {"label": fmt_notional(axis_max * i / 4), "left": round(i / 4 * 100, 3)}
        for i in range(5)
    ]

    scenarios = [
        {"title": s.title, "direction": s.direction, "body": s.body} for s in m.scenarios
    ]
    key_levels = [
        {
            "price_label": fmt_price(kl.price),
            "label": kl.label,
            "notional_label": fmt_notional(kl.notional),
            "side": kl.side,
        }
        for kl in m.key_levels
    ]

    # ----- 偏りスコア (bias) widget context -----
    _names = {"funding": "ファンディング", "oi": "OI速度", "skew": "クラスター偏り", "smart": "スマートマネー"}
    unavailable = [_names[k] for k in ("funding", "oi", "skew", "smart") if not m.bias_available.get(k, False)]
    bias_ctx = {
        "score": f"{m.bias_score:+d}",
        "state": m.bias_state or "静観",
        "side": m.bias_side or "neutral",
        "label": m.bias_label,
        "gauge_pct": round(max(0.0, min(100.0, (m.bias_score + 100) / 2.0)), 1),
        "fire_threshold": FIRE_SCORE,
        "unavailable": "・".join(unavailable),
    }

    return {
        "bias": bias_ctx,
        "title": m.title,
        "subtitle": m.subtitle,
        "asset": m.asset,
        "quote": m.quote,
        "current_price_label": fmt_price(m.current_price),
        "bands": bands,
        "y_labels": y_labels,
        "price_line": {"label": fmt_price(m.current_price), "top": y_pct(m.current_price)},
        "x_ticks": x_ticks,
        "axis_caption": m.axis_caption,
        "scenarios": scenarios,
        "key_levels": key_levels,
        "mood_chips": m.mood_chips,
        "author_name": m.author_name,
        "author_handle": m.author_handle,
        "source_label": m.source_label,
        "as_of": m.as_of,
        "disclaimer": m.disclaimer,
        "meta_tag": ("サンプル（数値はillustrative）" if m.is_sample else m.source_note),
    }


def render_html(m: LiquidationMap) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    return env.get_template("map.html.j2").render(**build_context(m))


# ----- screenshot ----------------------------------------------------------
async def render_png_async(m: LiquidationMap, out_path: str | Path, scale: int = 2) -> Path:
    from playwright.async_api import async_playwright

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(m)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=scale
        )
        await page.set_content(html, wait_until="networkidle")
        await page.evaluate("async () => { await document.fonts.ready; }")
        await page.wait_for_timeout(150)
        card = await page.query_selector("#card")
        await card.screenshot(path=str(out_path))
        await browser.close()

    return out_path


def render_png(m: LiquidationMap, out_path: str | Path, scale: int = 2) -> Path:
    """Synchronous wrapper around :func:`render_png_async`."""
    return asyncio.run(render_png_async(m, out_path, scale))

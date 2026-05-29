"""Aggregate a Hyperliquid position Snapshot into a renderable LiquidationMap.

Bucket every position's notional by its *liquidation price* into bands, then
derive the headline levels (primary trigger / largest cluster / upside wall),
auto-write the scenario blurbs, and assemble the mood chips.
"""

from __future__ import annotations

import math

from .models import Band, KeyLevel, LiquidationMap, Scenario
from .render import fmt_notional, fmt_price
from .sources.hyperliquid import Snapshot

_NICE_BANDS = [50, 100, 250, 500, 1000, 2000, 2500, 5000, 10000]


def _nice_band(x: float) -> int:
    return min(_NICE_BANDS, key=lambda c: abs(c - x))


def build_liquidation_map(
    snap: Snapshot,
    *,
    window_pct: float = 0.15,
    target_bands: int = 22,
    fng: dict | None = None,
    author_name: str = "仮想NISHI",
    author_handle: str = "@Nishi8maru",
    source_label: str = "Hyperliquid Liquidation Cascade Monitor",
) -> LiquidationMap:
    price = snap.price
    lower, upper = price * (1 - window_pct), price * (1 + window_pct)
    band = _nice_band((upper - lower) / target_bands)
    lo_b = int(math.floor(lower / band) * band)
    hi_b = int(math.ceil(upper / band) * band)
    levels = list(range(lo_b, hi_b + band, band))

    longs: dict[int, float] = {}
    shorts: dict[int, float] = {}
    for pos in snap.positions:
        if not (lower <= pos.liq_px <= upper):
            continue
        b = int(round(pos.liq_px / band) * band)
        bucket = longs if pos.side == "long" else shorts
        bucket[b] = bucket.get(b, 0.0) + pos.notional

    bands_all = [Band(p, longs.get(p, 0.0), shorts.get(p, 0.0)) for p in levels]

    # Trim outer all-zero bands but always keep the current price inside the frame.
    nz = [i for i, b in enumerate(bands_all) if b.total > 0]
    if nz:
        price_i = min(range(len(bands_all)), key=lambda i: abs(bands_all[i].price - price))
        lo_i, hi_i = min(min(nz), price_i), max(max(nz), price_i)
        bands = bands_all[lo_i : hi_i + 1]
    else:
        bands = bands_all

    max_notional = max((b.notional for b in bands), default=0.0)
    longs_b = [b for b in bands if b.price < price and b.long_notional > 0]
    shorts_b = [b for b in bands if b.price > price and b.short_notional > 0]

    trigger = None
    if longs_b:
        max_long = max(b.long_notional for b in longs_b)
        near = sorted((b for b in longs_b if b.long_notional >= 0.5 * max_long), key=lambda b: -b.price)
        trigger = near[0] if near else max(longs_b, key=lambda b: b.long_notional)
    wall = max(shorts_b, key=lambda b: b.short_notional) if shorts_b else None
    maxc = max(bands, key=lambda b: b.notional) if max_notional > 0 else None

    key_levels: list[KeyLevel] = []
    seen: set[int] = set()

    def add(b: Band | None, label: str, side: str, notional: float):
        if b is None or b.price in seen:
            return
        seen.add(b.price)
        key_levels.append(KeyLevel(b.price, label, notional, side))

    add(trigger, "一次トリガー", "long", trigger.long_notional if trigger else 0)
    if maxc:
        add(maxc, "最大クラスター", maxc.dominant_side, maxc.notional)
    add(wall, "上値の壁", "short", wall.short_notional if wall else 0)

    # Always surface up to 3 distinct headline levels (fill with next-largest).
    if len(key_levels) < 3:
        for b in sorted(bands, key=lambda x: -x.notional):
            if len(key_levels) >= 3:
                break
            if b.notional > 0:
                add(b, "主要クラスター", b.dominant_side, b.notional)

    scenarios: list[Scenario] = []
    if trigger:
        body = f"{fmt_price(trigger.price)} を割ると約 {fmt_notional(trigger.long_notional)} のロングが連鎖清算。"
        if maxc and maxc.price != trigger.price and maxc.dominant_side == "long":
            body += f" 売り圧力が {fmt_price(maxc.price)} の {fmt_notional(maxc.notional)} クラスターを誘発し下落を加速。"
        scenarios.append(Scenario("下値リスク", "down", body))
    if wall:
        scenarios.append(
            Scenario("上値の踏み上げ", "up", f"{fmt_price(wall.price)} 突破で約 {fmt_notional(wall.short_notional)} のショートが踏み上げ。")
        )
    if not scenarios:
        scenarios.append(Scenario("様子見", "down", "現値付近に大きな清算クラスターは検出されていません。"))

    chips: list[str] = []
    if fng:
        chips.append(f"Fear & Greed {fng['value']}")
    chips.append(f"Funding {snap.funding * 24 * 365 * 100:+.1f}%/yr")
    chips.append(f"OI {fmt_notional(snap.open_interest * price)}")

    return LiquidationMap(
        asset="BTC",
        quote="USD",
        current_price=price,
        bands=bands,
        scenarios=scenarios,
        key_levels=key_levels,
        mood_chips=chips,
        as_of=snap.as_of,
        author_name=author_name,
        author_handle=author_handle,
        source_label=source_label,
        is_sample=False,
        source_note=f"{snap.scanned:,}アドレス走査・{snap.btc_count} BTC建玉",
    )


def build_caption(m: LiquidationMap) -> str:
    """Compact social caption kept within X's 280-weighted limit (CJK counts 2)."""
    lines = [f"📊 BTC清算予兆モニター  {fmt_price(m.current_price)}", ""]
    for kl in m.key_levels[:3]:
        emoji = "🔴" if kl.side == "long" else "🟢"
        lines.append(f"{emoji} {fmt_price(kl.price)} {kl.label} {fmt_notional(kl.notional)}")
    lines += ["", "※清算予測・投資助言ではありません", "#BTC #Hyperliquid #清算"]
    return "\n".join(lines)

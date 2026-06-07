"""Aggregate a Hyperliquid position Snapshot into a renderable LiquidationMap.

Bucket every position's notional by its *liquidation price* into bands, then
derive the headline levels (primary trigger / largest cluster / upside wall),
auto-write the scenario blurbs, and assemble the mood chips.
"""

from __future__ import annotations

import math

from .bias import WATCH_SCORE, Inputs, evaluate
from .llm import generate_texts
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
    use_llm: bool = False,
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

    # Optional LLM rephrasing of the prose (numbers stay deterministic). Falls back
    # to the templates above if every provider fails.
    caption_comment = ""
    if use_llm:
        facts = {
            "現在値": round(price),
            "Funding年率%": round(snap.funding * 24 * 365 * 100, 1),
            "FearGreed": (fng.get("value") if fng else None),
            "走査アドレス数": snap.scanned,
            "BTC建玉数": snap.btc_count,
            "主要レベル": [
                {
                    "価格": kl.price,
                    "ラベル": kl.label,
                    "想定額M": round(kl.notional / 1e6, 1),
                    "サイド": "ロング" if kl.side == "long" else "ショート",
                }
                for kl in key_levels
            ],
        }
        texts = generate_texts(facts)
        if texts:
            for s in scenarios:
                if s.direction == "down":
                    s.body = texts["down"]
                elif s.direction == "up":
                    s.body = texts["up"]
            caption_comment = texts["caption"]
            print(f"[llm] commentary via {texts.get('_provider')}")

        # Quality floor: if the model returns generic filler (or nothing), use a
        # deterministic, data-driven one-liner so the public caption is specific.
        _filler = ("注視", "しましょう", "動向", "見守", "様子を見", "注目", "重要です")
        if not caption_comment or len(caption_comment) < 8 or any(f in caption_comment for f in _filler):
            if trigger:
                caption_comment = f"{fmt_price(trigger.price)}割れで約{fmt_notional(trigger.long_notional)}のロング清算が点火しやすい水準。"
            elif wall:
                caption_comment = f"{fmt_price(wall.price)}突破で約{fmt_notional(wall.short_notional)}のショート踏み上げに警戒。"

    chips: list[str] = []
    if fng:
        chips.append(f"Fear & Greed {fng['value']}")
    chips.append(f"Funding {snap.funding * 24 * 365 * 100:+.1f}%/yr")
    chips.append(f"OI {fmt_notional(snap.open_interest * price)}")

    # ----- 偏りスコア (bias score; see liqmap.bias / SPEC.md) -----
    long_total = sum(p.notional for p in snap.positions if p.side == "long" and p.liq_px < price)
    short_total = sum(p.notional for p in snap.positions if p.side == "short" and p.liq_px > price)
    cluster_list: list[tuple[float, str, float]] = []
    for b in bands:
        if b.long_notional > 0:
            cluster_list.append((b.price, "long", b.long_notional))
        if b.short_notional > 0:
            cluster_list.append((b.price, "short", b.short_notional))
    bias = evaluate(
        Inputs(
            price=price,
            price_24h_ago=snap.price_24h_ago or price,
            funding_8h=snap.funding * 8,  # HL funding is hourly -> 8h
            oi_now=snap.open_interest,
            oi_24h_ago=None,  # TODO: needs an OI time-series store (SPEC §6)
            long_cluster_total=long_total,
            short_cluster_total=short_total,
            clusters=cluster_list,
            smart_money_net=None,  # TODO: Nansen (SPEC §6)
        )
    )
    _bscore, _bside = bias["score"], bias["side"]
    if _bside == "neutral":
        bias_label = "中立"
    elif abs(_bscore) >= WATCH_SCORE:
        bias_label = "ロング過熱・下落カスケード警戒" if _bside == "long" else "ショート過熱・上踏み警戒"
    else:
        bias_label = "中立〜やや下値リスク優勢" if _bside == "long" else "中立〜やや上値リスク優勢"

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
        caption_comment=caption_comment,
        bias_score=bias["score"],
        bias_state=bias["state"],
        bias_side=bias["side"],
        bias_label=bias_label,
        bias_components=bias["components"],
        bias_available=bias["available"],
        bias_gate=bias["gate"],
    )


def _weighted(text: str) -> int:
    return sum(2 if ord(c) >= 0x1100 else 1 for c in text)


def _fit_weighted(text: str, budget: int) -> str:
    if budget < 8:
        return ""
    if _weighted(text) <= budget:
        return text
    out, w = [], 0
    for c in text:
        cw = 2 if ord(c) >= 0x1100 else 1
        if w + cw > budget - 1:
            break
        out.append(c)
        w += cw
    return "".join(out) + "…"


def build_caption(m: LiquidationMap) -> str:
    """Compact social caption kept within X's 280-weighted limit (CJK counts 2).

    The optional LLM one-liner is trimmed to whatever budget is left AFTER the
    fixed parts, so the disclaimer and hashtags are never the thing that gets cut.
    """
    head = [f"📊 BTC清算予兆モニター  {fmt_price(m.current_price)}", ""]
    for kl in m.key_levels[:3]:
        emoji = "🔴" if kl.side == "long" else "🟢"
        head.append(f"{emoji} {fmt_price(kl.price)} {kl.label} {fmt_notional(kl.notional)}")
    tail = ["", "※清算予測・投資助言ではありません", "#BTC #Hyperliquid #清算"]

    comment: list[str] = []
    if m.caption_comment:
        fitted = _fit_weighted(m.caption_comment, 275 - _weighted("\n".join(head + [""] + tail)))
        if fitted:
            comment = ["", fitted]
    return "\n".join(head + comment + tail)

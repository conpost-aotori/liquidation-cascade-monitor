"""Illustrative sample data that mirrors the reference mockup.

Numbers are fictional ("illustrative"), but the *shape* of this object is
exactly what the future Hyperliquid pipeline is meant to produce, so the
renderer can stay unchanged once real data is wired in.
"""

from __future__ import annotations

from .models import Band, KeyLevel, LiquidationMap, Scenario

M = 1_000_000  # notional is stored in raw USD

# Long liquidations sit *below* price (they fire on the way down).
_LONG_BANDS = {
    73_000: 175 * M,
    72_500: 210 * M,
    72_000: 345 * M,   # 一次トリガー
    71_500: 235 * M,
    71_000: 305 * M,
    70_500: 470 * M,
    70_000: 540 * M,   # 最大クラスター
    69_500: 300 * M,
    69_000: 250 * M,
    68_500: 285 * M,
    68_000: 255 * M,
}

# Short liquidations sit *above* price (they fire on the way up).
_SHORT_BANDS = {
    73_500: 120 * M,
    74_000: 195 * M,
    74_500: 235 * M,
    75_000: 250 * M,   # 上値の壁
    75_500: 150 * M,
    76_000: 95 * M,
    76_500: 78 * M,
    77_000: 60 * M,
}


def sample_map() -> LiquidationMap:
    bands = [Band(price=p, long_notional=n) for p, n in _LONG_BANDS.items()]
    bands += [Band(price=p, short_notional=n) for p, n in _SHORT_BANDS.items()]
    bands.sort(key=lambda b: b.price)

    return LiquidationMap(
        asset="BTC",
        quote="USD",
        current_price=73_400,
        bands=bands,
        key_levels=[
            KeyLevel(72_000, "一次トリガー", 345 * M, "long"),
            KeyLevel(70_000, "最大クラスター", 540 * M, "long"),
            KeyLevel(75_000, "上値の壁", 250 * M, "short"),
        ],
        scenarios=[
            Scenario(
                "下値リスク",
                "down",
                "$72,000 を割ると約 $345M のロングが連鎖清算 → 売り圧力が "
                "$70,000 の $540M クラスターを誘発し、さらなる下落を加速。",
            ),
            Scenario(
                "上値の踏み上げ",
                "up",
                "$75,000 突破で約 $250M のショートが踏み上げ。"
                "直近でブルが防衛した節目と一致。",
            ),
        ],
        mood_chips=["ETF流出 8日連続", "Fear & Greed 22", "リスクオフ"],
        as_of="2026-05-29",
        author_name="仮想NISHI",
        author_handle="@Nishi8maru",
        source_label="Hyperliquid Liquidation Cascade Monitor",
        is_sample=True,
    )

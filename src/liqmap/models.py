"""Data model for a BTC liquidation-cascade map.

Everything the renderer needs is captured here. Notional amounts are stored as
raw USD floats (e.g. ``540_000_000``) so the model lines up 1:1 with what the
future Hyperliquid pipeline will emit — the renderer does the M/B formatting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["long", "short"]
ScenarioDir = Literal["down", "up"]


@dataclass
class Band:
    """A single price band and the notional liquidation value sitting in it.

    Longs liquidate on the way *down*; shorts liquidate on the way *up*. A band
    can hold both, but in practice one side dominates and that is what gets drawn.
    """

    price: float
    long_notional: float = 0.0
    short_notional: float = 0.0

    @property
    def total(self) -> float:
        return self.long_notional + self.short_notional

    @property
    def dominant_side(self) -> Side:
        return "long" if self.long_notional >= self.short_notional else "short"

    @property
    def notional(self) -> float:
        """Notional of the dominant side — the value drawn for this band."""
        return max(self.long_notional, self.short_notional)


@dataclass
class KeyLevel:
    """A highlighted level shown both as a chart annotation and a panel row.

    ``label`` is the editorial tag (e.g. "一次トリガー"). List order is display
    order in the right-hand panel — it is intentionally *not* sorted by price.
    """

    price: float
    label: str
    notional: float
    side: Side


@dataclass
class Scenario:
    """A short narrative block in the right-hand panel."""

    title: str
    direction: ScenarioDir  # "down" -> red dot, "up" -> green dot
    body: str


@dataclass
class LiquidationMap:
    """The full payload for one rendered card."""

    asset: str
    quote: str
    current_price: float
    bands: list[Band]
    scenarios: list[Scenario]
    key_levels: list[KeyLevel]
    mood_chips: list[str]
    as_of: str  # ISO date string, e.g. "2026-05-29"
    author_name: str
    author_handle: str
    source_label: str
    is_sample: bool = True
    source_note: str = ""  # shown next to the date (e.g. scan size) for live data
    caption_comment: str = ""  # optional LLM-written one-liner for the social caption
    disclaimer: str = "※清算予測であり投資助言ではありません"
    title: str = "BTC清算予兆モニター"
    subtitle: str = "Hyperliquid Perps ／ 大口ポジション清算クラスター"
    axis_caption: str = "価格帯ごとの清算想定額 (notional)"

    # ----- derived helpers -------------------------------------------------
    @property
    def price_min(self) -> float:
        return min(b.price for b in self.bands)

    @property
    def price_max(self) -> float:
        return max(b.price for b in self.bands)

    @property
    def band_step(self) -> float:
        """Smallest gap between adjacent band prices (the grid resolution)."""
        prices = sorted(b.price for b in self.bands)
        gaps = [b - a for a, b in zip(prices, prices[1:]) if b - a > 0]
        return min(gaps) if gaps else 500.0

    @property
    def max_notional(self) -> float:
        return max((b.notional for b in self.bands), default=0.0)

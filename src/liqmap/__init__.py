"""liqmap — BTC liquidation-cascade map generator.

This session implements the *visual* layer only: turn a `LiquidationMap`
(see :mod:`liqmap.models`) into a polished PNG that mirrors the reference
mockup. The same data shape is intended to be produced later by the real
Hyperliquid pipeline, so the renderer stays decoupled from any data source.
"""

from .models import Band, KeyLevel, LiquidationMap, Scenario

__all__ = ["Band", "KeyLevel", "LiquidationMap", "Scenario"]

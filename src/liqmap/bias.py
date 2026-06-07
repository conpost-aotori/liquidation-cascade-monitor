"""偏りスコア — liquidation-cascade direction predictor (canonical logic).

Sign convention (must match the red=long / green=short dashboard colours):
    +100 ← shorts crowded → upside squeeze risk          (green / up)
       0 ← neutral
    -100 ← longs crowded  → downside cascade risk         (red / down)

This is the reference implementation from SPEC.md §5. Verified by scripts/test_bias.py
(SPEC §10 vectors). `evaluate()` is the convenience entry the pipeline calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ===== Tunables (calibrate via backtest; all magic numbers live here) =====
W_FUNDING, W_OI, W_SKEW, W_SMART = 40, 25, 20, 15
FUNDING_CAP_8H = 0.0005   # 0.05%/8h ≈ 55% APR = overheated ceiling
OI_VEL_CAP = 0.10         # +10% 24h OI = full marks
STRESS_AGAINST = 1.0      # price moving against the crowded side → max stress
STRESS_WITH = 0.6         # price moving with the crowded side → damped
GATE_DIST = 0.02          # nearest dense cluster within 2%
GATE_DENSITY = 0.25       # "dense" = >= 25% of same-side total
GATE_ABS_FLOOR = 20e6     # ...or an absolute USD floor
FIRE_SCORE = 60
WATCH_SCORE = 40


@dataclass
class Inputs:
    price: float
    price_24h_ago: float          # Hyperliquid prevDayPx
    funding_8h: float             # 8h-equivalent funding (decimal); HL is hourly so ×8
    oi_now: float
    oi_24h_ago: Optional[float]   # None if no snapshot history yet
    long_cluster_total: float     # total long-liq notional below price
    short_cluster_total: float    # total short-liq notional above price
    clusters: List[Tuple[float, str, float]]  # [(price, 'long'|'short', notional), ...]
    smart_money_net: Optional[float]  # [-1,1], + = smart net long; None if absent


def _components(x: Inputs) -> Tuple[float, float, float, float]:
    # C1: funding (the side paying = crowded = fragile)
    c1 = clamp(-x.funding_8h / FUNDING_CAP_8H, -1, 1) * W_FUNDING

    # C2: OI velocity × direction (is the crowding actively building?)
    if x.oi_24h_ago:
        oi_chg = (x.oi_now - x.oi_24h_ago) / x.oi_24h_ago
        oi_vel = clamp(oi_chg / OI_VEL_CAP, 0, 1)        # only increases raise fragility
        direction = -1 if x.funding_8h > 0 else 1        # crowded side (funding sign)
        px_chg = (x.price - x.price_24h_ago) / x.price_24h_ago
        against = (x.funding_8h > 0 and px_chg < 0) or (x.funding_8h < 0 and px_chg > 0)
        stress = STRESS_AGAINST if against else STRESS_WITH
        c2 = oi_vel * direction * stress * W_OI
    else:
        c2 = 0.0

    # C3: cluster skew (up/down asymmetry of position distribution)
    denom = x.short_cluster_total + x.long_cluster_total
    skew = (x.short_cluster_total - x.long_cluster_total) / denom if denom else 0.0
    c3 = clamp(skew, -1, 1) * W_SKEW

    # C4: smart-money divergence (Nansen)
    c4 = clamp(x.smart_money_net, -1, 1) * W_SMART if x.smart_money_net is not None else 0.0

    return c1, c2, c3, c4


def bias_score(x: Inputs) -> int:
    return round(sum(_components(x)))


def cascade_gate(x: Inputs, score: int) -> dict:
    if score < 0:                       # longs fragile → downside long clusters
        side, below, total = "long", True, x.long_cluster_total
    else:                               # shorts fragile → upside short clusters
        side, below, total = "short", False, x.short_cluster_total
    threshold = max(GATE_DENSITY * total, GATE_ABS_FLOOR)
    cand = []
    for p, s, n in x.clusters:
        if s != side:
            continue
        if below and p < x.price:
            cand.append(((x.price - p) / x.price, p, n))
        elif (not below) and p > x.price:
            cand.append(((p - x.price) / x.price, p, n))
    cand.sort()                         # nearest first
    for dist, p, n in cand:
        if n >= threshold:              # nearest "dense" one is the trigger
            return {"open": dist <= GATE_DIST, "trigger_px": p,
                    "dist": round(dist, 4), "notional": n}
    return {"open": False, "trigger_px": None, "dist": None, "notional": 0}


def state(score: int, gate: dict) -> str:
    if abs(score) >= FIRE_SCORE and gate["open"]:
        return "発火"
    if abs(score) >= WATCH_SCORE or gate["open"]:
        return "監視"
    return "静観"


def evaluate(x: Inputs) -> dict:
    """Convenience entry: score + per-component breakdown + gate + state + side."""
    c1, c2, c3, c4 = _components(x)
    score = round(c1 + c2 + c3 + c4)
    g = cascade_gate(x, score)
    return {
        "score": score,
        "components": {"funding": c1, "oi": c2, "skew": c3, "smart": c4},
        "available": {
            "funding": True,
            "oi": x.oi_24h_ago is not None,
            "skew": (x.short_cluster_total + x.long_cluster_total) > 0,
            "smart": x.smart_money_net is not None,
        },
        "gate": g,
        "state": state(score, g),
        "side": "short" if score > 0 else "long" if score < 0 else "neutral",
    }

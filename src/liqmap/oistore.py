"""Tiny OI time-series store for the bias C2 term (OI velocity).

Hyperliquid exposes no prevDayOI, so we persist current OI each run and look up
the value ~24h ago. In CI this file is round-tripped via the Actions cache.
Returns None until ~24h of history exists (cold start) -> C2 contributes 0.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_PATH = "out/cache/oi_history.json"


def update_and_get_24h(
    oi_now: float,
    path: str | Path = DEFAULT_PATH,
    *,
    now_ts: float | None = None,
    window_h: float = 24.0,
    tol_h: float = 4.0,
    keep_h: float = 50.0,
) -> float | None:
    """Append (now, oi_now) to the store and return the OI closest to 24h ago.

    Returns None if no sample falls within ±tol_h of the 24h-ago target.
    """
    now_ts = now_ts if now_ts is not None else time.time()
    p = Path(path)

    hist: list[list[float]] = []
    if p.exists():
        try:
            hist = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            hist = []

    target = now_ts - window_h * 3600
    best_oi, best_dt = None, tol_h * 3600 + 1
    for ts, oi in hist:
        dt = abs(ts - target)
        if dt < best_dt:
            best_dt, best_oi = dt, oi
    oi_24h = best_oi if best_dt <= tol_h * 3600 else None

    hist.append([now_ts, oi_now])
    cutoff = now_ts - keep_h * 3600
    hist = [[ts, oi] for ts, oi in hist if ts >= cutoff]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(hist), encoding="utf-8")

    return oi_24h

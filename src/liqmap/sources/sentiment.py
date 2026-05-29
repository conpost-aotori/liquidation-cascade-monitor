"""Lightweight, free sentiment feeds for the 'mood' chips. All best-effort."""

from __future__ import annotations

import httpx


def fetch_fear_greed() -> dict | None:
    """Crypto Fear & Greed index from alternative.me (free, no key)."""
    try:
        r = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception:
        return None

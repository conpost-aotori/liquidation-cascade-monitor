"""Hyperliquid public-API client + position snapshot builder.

Strategy (see the `hl-data-reality` notes):
  1. Pull the public leaderboard purely as an *address universe* (~37.5k addrs).
     Its `accountValue` is stale, so we never use it for sizing.
  2. Query `clearinghouseState` per address (concurrently, rate-tolerant) and
     keep every live BTC perp position that has a `liquidationPx`.
  3. Cache the raw snapshot to disk so re-renders don't re-crawl.

Longs liquidate on the way down (liqPx < price); shorts on the way up.
"""

from __future__ import annotations

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
CACHE_DIR = Path("out/cache")


@dataclass
class Position:
    address: str
    side: str  # "long" | "short"
    size: float
    liq_px: float
    notional: float
    entry_px: float | None = None
    leverage: float | None = None
    margin_type: str | None = None


@dataclass
class Snapshot:
    price: float  # BTC mark price at snapshot time
    oracle_px: float
    open_interest: float  # in BTC
    funding: float  # hourly rate
    positions: list[Position]
    scanned: int
    as_of: str  # ISO-ish UTC string
    price_24h_ago: float = 0.0  # Hyperliquid prevDayPx (for bias OI/price-direction term)
    smart_money_net: float | None = None  # winners' BTC net (long-short)/(long+short), [-1,1]

    @property
    def btc_count(self) -> int:
        return len(self.positions)


# ----- low-level calls -----------------------------------------------------
def _post(client: httpx.Client, payload: dict, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            r = client.post(INFO_URL, json=payload)
            if r.status_code == 429:
                time.sleep(0.4 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))
                continue
            raise
    return None


def fetch_market(client: httpx.Client) -> dict:
    """Return BTC market context: mark/oracle price, open interest, funding."""
    meta = _post(client, {"type": "metaAndAssetCtxs"})
    universe = meta[0]["universe"]
    ctxs = meta[1]
    idx = next(i for i, u in enumerate(universe) if u["name"] == "BTC")
    ctx = ctxs[idx]
    return {
        "mark": float(ctx["markPx"]),
        "oracle": float(ctx.get("oraclePx", ctx["markPx"])),
        "prev_day": float(ctx.get("prevDayPx", ctx["markPx"])),
        "open_interest": float(ctx.get("openInterest", 0)),
        "funding": float(ctx.get("funding", 0)),
    }


def fetch_leaderboard_rows(client: httpx.Client, *, refresh: bool = False,
                           cache_ttl: int = 86_400) -> list[list]:
    """Return [[ethAddress, allTimePnl], ...] — address universe + winner ranking."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "leaderboard_rows.json"
    if cache.exists() and not refresh and time.time() - cache.stat().st_mtime < cache_ttl:
        return json.loads(cache.read_text(encoding="utf-8"))
    r = client.get(LEADERBOARD_URL, headers={"User-Agent": "liqmap/1.0"}, timeout=120)
    r.raise_for_status()
    rows = []
    for row in r.json()["leaderboardRows"]:
        perf = dict(row.get("windowPerformances") or [])
        try:
            pnl = float((perf.get("allTime") or {}).get("pnl", 0) or 0)
        except Exception:
            pnl = 0.0
        rows.append([row["ethAddress"], pnl])
    cache.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def _extract_btc(address: str, state: dict) -> Position | None:
    for ap in state.get("assetPositions", []):
        p = ap.get("position", {})
        if p.get("coin") != "BTC":
            continue
        szi = float(p.get("szi", 0) or 0)
        liq = p.get("liquidationPx")
        if szi == 0 or liq is None:
            return None
        lev = p.get("leverage") or {}
        return Position(
            address=address,
            side="long" if szi > 0 else "short",
            size=abs(szi),
            liq_px=float(liq),
            notional=float(p.get("positionValue", 0) or 0),
            entry_px=float(p["entryPx"]) if p.get("entryPx") else None,
            leverage=float(lev.get("value")) if lev.get("value") is not None else None,
            margin_type=lev.get("type"),
        )
    return None


# ----- snapshot ------------------------------------------------------------
def fetch_snapshot(*, max_addresses: int = 0, concurrency: int = 25, refresh: bool = False,
                   seed: int = 7, cache_ttl: int = 1_800, verbose: bool = True) -> Snapshot:
    """Crawl positions and return a Snapshot. ``max_addresses=0`` means all.

    Results are cached by (max_addresses, seed); pass ``refresh=True`` to recrawl.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"snapshot_{max_addresses}_{seed}.json"
    if cache.exists() and not refresh and time.time() - cache.stat().st_mtime < cache_ttl:
        d = json.loads(cache.read_text(encoding="utf-8"))
        d["positions"] = [Position(**p) for p in d["positions"]]
        if verbose:
            print(f"[cache] {cache.name}: {len(d['positions'])} BTC positions")
        return Snapshot(**d)

    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency)
    with httpx.Client(timeout=30, limits=limits, headers={"Content-Type": "application/json"}) as client:
        market = fetch_market(client)
        rows = fetch_leaderboard_rows(client, refresh=refresh)
        # "Winners" = top 20% by all-time PnL (HL-native smart-money proxy for bias C4).
        ranked = sorted(rows, key=lambda r: r[1], reverse=True)
        winners = {a for a, _ in ranked[: max(1, len(ranked) // 5)]}
        addrs = [a for a, _ in rows]
        if max_addresses and max_addresses < len(addrs):
            random.seed(seed)
            addrs = random.sample(addrs, max_addresses)
        total = len(addrs)
        if verbose:
            print(f"[crawl] scanning {total:,} addresses @ conc={concurrency} ({len(winners):,} winners) ...")

        positions: list[Position] = []
        smart = {"long": 0.0, "short": 0.0}  # winners' BTC notional by side
        errors = 0
        done = 0
        lock = threading.Lock()
        t0 = time.time()

        def work(a: str):
            nonlocal errors, done
            try:
                st = _post(client, {"type": "clearinghouseState", "user": a})
                pos = _extract_btc(a, st) if st else None
            except Exception:
                pos = None
                with lock:
                    errors += 1
            with lock:
                done += 1
                if pos:
                    positions.append(pos)
                    if a in winners:
                        smart[pos.side] += pos.notional
                if verbose and done % 2000 == 0:
                    rate = done / max(time.time() - t0, 1e-6)
                    print(f"  {done:,}/{total:,} ({rate:.0f}/s) - {len(positions)} BTC positions, {errors} errs")
            return pos

        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            list(ex.map(work, addrs))

        _wtot = smart["long"] + smart["short"]
        smart_money_net = (smart["long"] - smart["short"]) / _wtot if _wtot > 0 else None

    snap = Snapshot(
        price=market["mark"],
        oracle_px=market["oracle"],
        open_interest=market["open_interest"],
        funding=market["funding"],
        positions=positions,
        scanned=total,
        as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        price_24h_ago=market["prev_day"],
        smart_money_net=smart_money_net,
    )
    out = asdict(snap)
    cache.write_text(json.dumps(out), encoding="utf-8")
    if verbose:
        print(f"[crawl] done in {time.time() - t0:.0f}s: {len(positions)} BTC positions "
              f"({errors} errors) -> {cache.name}")
    return snap

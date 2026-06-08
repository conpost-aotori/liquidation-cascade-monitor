#!/usr/bin/env python
"""Crawl Hyperliquid and persist ONLY the bias score to out/bias_log.jsonl.

NO render, NO X/Discord posting, NO secrets. This is the lightweight collector
used by the bias-collect workflow to build the forward-only bias time series
for downstream consumers (hl-swing-bot's feature store), independent of the
X-posting pipeline in post.yml / generate.py.

build_liquidation_map() appends the bias record to out/bias_log.jsonl as a side
effect (see liqmap.biaslog); we just discard the returned map (no render).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Crawl + persist bias (no render/post).")
    ap.add_argument("--max-addresses", type=int, default=4000,
                    help="cap leaderboard addresses scanned (4000 ~3min; 0=full ~28min)")
    ap.add_argument("--concurrency", type=int, default=25)
    ap.add_argument("--window", type=float, default=0.15)
    ap.add_argument("--refresh", action="store_true", help="ignore cache and recrawl")
    args = ap.parse_args()

    from liqmap.clusters import build_liquidation_map
    from liqmap.oistore import update_and_get_24h
    from liqmap.sources.hyperliquid import fetch_snapshot

    snap = fetch_snapshot(
        max_addresses=args.max_addresses,
        concurrency=args.concurrency,
        refresh=args.refresh,
    )
    oi_24h = update_and_get_24h(snap.open_interest)  # bias C2 (None until ~24h history)
    m = build_liquidation_map(
        snap, window_pct=args.window, fng=None, use_llm=False, oi_24h_ago=oi_24h
    )
    print(
        f"bias persisted: score={m.bias_score} side={m.bias_side} "
        f"state={m.bias_state} price=${m.current_price:,.0f} "
        f"scanned={snap.scanned:,} oi_fresh={oi_24h is not None}"
    )


if __name__ == "__main__":
    main()

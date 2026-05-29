#!/usr/bin/env python
"""Render the BTC liquidation-cascade map (sample or live Hyperliquid data).

Examples:
    # illustrative sample (instant)
    python scripts/generate.py

    # live data, quick scan of 4000 leaderboard addresses (~3 min)
    python scripts/generate.py --source live --max-addresses 4000

    # live, full crawl (~28 min), then post to Discord + X
    python scripts/generate.py --source live --post-discord --post-x

    # reuse the last cached crawl, just re-render
    python scripts/generate.py --source live --max-addresses 4000   # (cache hit)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp932 here; force UTF-8 so JP text / emoji / dashes print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from liqmap.render import render_html, render_png  # noqa: E402


def build_map(args):
    if args.source == "sample":
        from liqmap.sample_data import sample_map
        return sample_map()

    from liqmap.clusters import build_liquidation_map
    from liqmap.sources.hyperliquid import fetch_snapshot
    from liqmap.sources.sentiment import fetch_fear_greed

    snap = fetch_snapshot(
        max_addresses=args.max_addresses,
        concurrency=args.concurrency,
        refresh=args.refresh,
    )
    return build_liquidation_map(snap, window_pct=args.window, fng=fetch_fear_greed())


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the BTC liquidation-cascade map.")
    ap.add_argument("--source", choices=["sample", "live"], default="sample")
    ap.add_argument("--max-addresses", type=int, default=0, help="live: cap addresses scanned (0=all, ~28min)")
    ap.add_argument("--concurrency", type=int, default=25)
    ap.add_argument("--window", type=float, default=0.15, help="live: price window +/- fraction (default 0.15)")
    ap.add_argument("--refresh", action="store_true", help="live: ignore cache and recrawl")
    ap.add_argument("-o", "--out", default=None, help="output PNG path")
    ap.add_argument("--scale", type=int, default=2, help="device scale factor (default: 2)")
    ap.add_argument("--html", action="store_true", help="also dump the rendered HTML")
    ap.add_argument("--post-discord", action="store_true", help="post the result to Discord")
    ap.add_argument("--post-x", action="store_true", help="post the result to X")
    args = ap.parse_args()

    m = build_map(args)
    out = Path(args.out) if args.out else Path("out") / f"liqmap_{m.asset.lower()}_{args.source}.png"

    if args.html:
        html_path = out.with_suffix(".html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(m), encoding="utf-8")
        print(f"HTML  -> {html_path.resolve()}")

    path = render_png(m, out, scale=args.scale)
    print(f"PNG   -> {path.resolve()}  ({args.scale}x = {1600 * args.scale}x{900 * args.scale})")

    if args.post_discord or args.post_x:
        from liqmap.clusters import build_caption
        from liqmap import distribute
        caption = build_caption(m)
        print("\n--- caption ---\n" + caption + "\n---------------")
        if args.post_discord:
            distribute.post_discord(path, caption, live=True)
        if args.post_x:
            distribute.post_x(path, caption, live=True)


if __name__ == "__main__":
    main()

"""Append-only persistence of the bias score time series.

WHY: the rendered PNG/HTML and the cached snapshot_*.json are point-in-time
(overwritten each run), so there is no historical record of how the bias score
evolved. Downstream consumers (e.g. hl-swing-bot's feature store) need a
forward-only time series. This module appends one JSON line per build to
``out/bias_log.jsonl``.

DESIGN CONSTRAINTS:
- Purely additive. Never imported by distribute.py; has nothing to do with
  X/Discord posting.
- Defensive: append_bias() must NEVER raise — a logging failure must not break
  the render/post pipeline. All errors are swallowed with a warning.
- Append-only JSONL so concurrent/over-lapping runs can't corrupt prior rows.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def append_bias(
    out_dir: Path | str,
    *,
    as_of: str,
    price: float,
    bias: dict[str, Any],
    scanned: int | None = None,
    btc_count: int | None = None,
    filename: str = "bias_log.jsonl",
) -> bool:
    """Append one bias observation to the JSONL log. Returns True on success.

    ``bias`` is the dict returned by liqmap.bias.evaluate() — we persist its
    score, components, gate, state, side, and availability flags (the last are
    Codex's "data freshness markers": which components were live this run).
    """
    try:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": SCHEMA_VERSION,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "as_of": as_of,                       # source snapshot's date label
            "price": price,
            "score": bias.get("score"),
            "side": bias.get("side"),
            "state": bias.get("state"),
            "components": bias.get("components"),  # funding/oi/skew/smart contributions
            "available": bias.get("available"),    # freshness: which components were live
            "gate": bias.get("gate"),
            "scanned": scanned,
            "btc_count": btc_count,
        }
        line = json.dumps(record, ensure_ascii=False)
        with (out / filename).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception:  # never break the pipeline over a log write
        log.warning("biaslog: failed to append bias record", exc_info=True)
        return False

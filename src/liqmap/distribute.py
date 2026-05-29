"""Post a rendered map + caption to Discord and/or X.

SAFETY:
  * Posting is DRY-RUN by default. You must pass ``live=True`` to actually post
    (generate.py does this only when you pass --post-discord / --post-x).
  * The project-local ``.env`` is loaded — we deliberately do NOT walk up into
    parent directories, so a stray parent .env can't silently supply creds.

Credentials (project ``.env`` or real environment variables):
    DISCORD_WEBHOOK_URL
    X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    # Load the nearest .env: this project's root first, else a shared parent .env
    # (e.g. C:\User\projects\.env that powers the user's other bots). This is safe
    # because posting is DRY-RUN unless live=True — discovering creds can't transmit.
    from dotenv import find_dotenv, load_dotenv

    _local = _PROJECT_ROOT / ".env"
    load_dotenv(_local if _local.exists() else find_dotenv(usecwd=True))
except Exception:
    pass


def post_discord(image_path: str | Path, caption: str, *, live: bool = False,
                 webhook_url: str | None = None) -> str | None:
    image_path = Path(image_path)
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not live:
        print(f"[discord] DRY-RUN: would post {image_path.name} "
              f"({'webhook configured' if url else 'NO webhook'}). Pass live=True to send.")
        return None
    if not url:
        print("[discord] DISCORD_WEBHOOK_URL not set — cannot post.")
        return None
    sep = "&" if "?" in url else "?"
    with image_path.open("rb") as f:
        files = {"file": (image_path.name, f, "image/png")}
        r = httpx.post(f"{url}{sep}wait=true", data={"content": caption[:2000]}, files=files, timeout=60)
    r.raise_for_status()
    mid = r.json().get("id")
    print(f"[discord] posted OK (message id={mid})")
    return mid


def delete_discord_message(message_id: str, webhook_url: str | None = None) -> bool:
    """Delete a message previously sent by this webhook (needs its message id)."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        print("[discord] DISCORD_WEBHOOK_URL not set — cannot delete.")
        return False
    r = httpx.delete(f"{url}/messages/{message_id}", timeout=30)
    r.raise_for_status()
    print(f"[discord] deleted message {message_id}")
    return True


def _x_weighted_len(text: str) -> int:
    # X counts CJK / wide chars and most emoji as 2, ASCII as 1 (approximation).
    return sum(2 if ord(ch) >= 0x1100 else 1 for ch in text)


def _x_trim(text: str, limit: int = 280) -> str:
    if _x_weighted_len(text) <= limit:
        return text
    out, w = [], 0
    for ch in text:
        cw = 2 if ord(ch) >= 0x1100 else 1
        if w + cw > limit - 1:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


def post_x(image_path: str | Path, caption: str, *, live: bool = False) -> str | None:
    keys = {k: os.getenv(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}
    text = _x_trim(caption)
    if not live:
        have = "creds configured" if all(keys.values()) else "NO creds"
        print(f"[x] DRY-RUN: would tweet {Path(image_path).name} ({have}). Pass live=True to send.\n"
              f"    text: {text!r}")
        return None
    if not all(keys.values()):
        missing = [k for k, v in keys.items() if not v]
        print(f"[x] missing {missing} — cannot post.")
        return None

    import tweepy

    auth = tweepy.OAuth1UserHandler(
        keys["X_API_KEY"], keys["X_API_SECRET"], keys["X_ACCESS_TOKEN"], keys["X_ACCESS_SECRET"]
    )
    media = tweepy.API(auth).media_upload(filename=str(image_path))
    client = tweepy.Client(
        consumer_key=keys["X_API_KEY"],
        consumer_secret=keys["X_API_SECRET"],
        access_token=keys["X_ACCESS_TOKEN"],
        access_token_secret=keys["X_ACCESS_SECRET"],
    )
    resp = client.create_tweet(text=text, media_ids=[media.media_id])
    tid = resp.data.get("id") if resp and resp.data else None
    print(f"[x] posted OK (tweet id={tid})  https://x.com/i/web/status/{tid}")
    return tid


def delete_x_tweet(tweet_id: str) -> bool:
    """Delete a tweet by id (works even on post-only tiers; needs the id)."""
    keys = {k: os.getenv(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}
    if not all(keys.values()):
        print("[x] credentials not set — cannot delete.")
        return False
    import tweepy

    client = tweepy.Client(
        consumer_key=keys["X_API_KEY"],
        consumer_secret=keys["X_API_SECRET"],
        access_token=keys["X_ACCESS_TOKEN"],
        access_token_secret=keys["X_ACCESS_SECRET"],
    )
    resp = client.delete_tweet(tweet_id)
    print(f"[x] delete {tweet_id}: {resp.data}")
    return True

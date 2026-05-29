"""LLM commentary with Gemini -> OpenAI -> Grok fallback.

Only the *prose* is model-written; every number/level is computed deterministically
upstream, so the model can only rephrase facts it is given. Returns None if all
providers fail, so callers fall back to the built-in templates. Used via REST
(httpx) — no provider SDKs required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import find_dotenv, load_dotenv

    _local = _PROJECT_ROOT / ".env"
    load_dotenv(_local if _local.exists() else find_dotenv(usecwd=True))
except Exception:
    pass

# Models (configurable; first that responds wins).
GEMINI_MODEL = "gemini-2.0-flash"
OPENAI_MODEL = "gpt-4o-mini"
GROK_MODEL = "grok-2-latest"

_SYSTEM = (
    "あなたはHyperliquidの清算データを解説する暗号資産アナリストです。"
    "与えられた数値のみを根拠に、簡潔で中立的な日本語を書きます。"
    "投資助言・売買推奨・断定的な価格予測はしない。与えられていない数値や事実を作らない。誇張や煽りを避ける。"
)


def _prompt(facts: dict) -> str:
    return (
        "以下はBTC無期限の清算クラスター集計（実データ）です。\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
        + "\n\nこの数値のみを使い、次のキーを持つJSONを日本語で出力してください。\n"
        "価格は必ず $68,000 のように $ とカンマ区切り、金額は $109M のように表記する。\n"
        '{"down": "下値リスクの解説(70字以内・一次トリガーと最大クラスターの価格と金額に具体的に言及)", '
        '"up": "上値の踏み上げの解説(70字以内・上値の壁の価格と金額に具体的に言及)", '
        '"caption": "X用の一言の読み(35字以内・事実ベースで端的に。『注視しましょう』等の定型句や助言調は禁止。絵文字/ハッシュタグ不要)"}\n'
        "JSONのみを出力。"
    )


def _parse(text: str | None) -> dict | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    try:
        d = json.loads(t)
    except Exception:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            return None
        try:
            d = json.loads(t[i : j + 1])
        except Exception:
            return None
    if not all(isinstance(d.get(k), str) and d.get(k).strip() for k in ("down", "up", "caption")):
        return None
    return {k: d[k].strip() for k in ("down", "up", "caption")}


def _gemini(facts: dict) -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": _prompt(facts)}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 400, "responseMimeType": "application/json"},
    }
    r = httpx.post(url, json=body, timeout=25)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai_compatible(base_url: str, key: str | None, model: str, facts: dict, json_mode: bool) -> str | None:
    if not key:
        return None
    body = {
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": _prompt(facts)}],
        "temperature": 0.7,
        "max_tokens": 400,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=25)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def generate_texts(facts: dict) -> dict | None:
    """Return {'down','up','caption','_provider'} or None if every provider fails."""
    grok_key = os.getenv("xAI_API_kEY") or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    providers = [
        ("gemini", lambda: _gemini(facts)),
        ("openai", lambda: _openai_compatible("https://api.openai.com/v1", os.getenv("OPENAI_API_KEY"), OPENAI_MODEL, facts, True)),
        ("grok", lambda: _openai_compatible("https://api.x.ai/v1", grok_key, GROK_MODEL, facts, False)),
    ]
    for name, fn in providers:
        try:
            parsed = _parse(fn())
        except Exception as e:
            print(f"[llm] {name} failed: {repr(e)[:140]}")
            continue
        if parsed:
            parsed["_provider"] = name
            return parsed
        print(f"[llm] {name} returned no usable JSON; trying next")
    print("[llm] all providers failed -> template fallback")
    return None

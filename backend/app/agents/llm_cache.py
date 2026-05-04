"""File-backed response cache for the Analyst's LLM calls.

Keyed by SHA256 of (provider, model, system, user). Lives under
`backend/.llm_cache/` (gitignored). The point is to make repeated demo runs
free during development — the same `(truck, load)` pair produces the same
prompt and therefore the same cache key.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings

CACHE_DIR = BACKEND_DIR / ".llm_cache"


def _key(provider: str, model: str, system: str, user: str) -> str:
    h = hashlib.sha256()
    for piece in (provider, model, system, user):
        h.update(piece.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _path(provider: str, model: str, system: str, user: str) -> Path:
    return CACHE_DIR / f"{_key(provider, model, system, user)}.json"


def get_cached(provider: str, model: str, system: str, user: str) -> str | None:
    if not get_settings().llm_cache_enabled:
        return None
    p = _path(provider, model, system, user)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))["response"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def put_cached(provider: str, model: str, system: str, user: str, response: str) -> None:
    if not get_settings().llm_cache_enabled:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(provider, model, system, user)
    payload = {"provider": provider, "model": model, "response": response}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

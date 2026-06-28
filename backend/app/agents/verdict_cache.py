"""On-disk verdict cache, keyed by the SEMANTIC features of (truck, load).

Why this exists
---------------
The LLM cache (`llm_cache.py`) keys responses by the SHA256 of the full
user-message sent to Gemini — which is good for byte-exact prompt reuse
but useless for skipping RAG retrieval. Today's `analyst_fleet()` flow:

    for each (truck, load):
        hard_rules → if blocked, skip LLM
        query_rules() + query_corpus()  ← ~600 ms each, sequential
        build user_message including retrieved chunks
        provider.evaluate()             ← hits LLM cache, fast on warm pairs
        sanity_layer()

So a fully warm cache still pays 31 × 2 × ~600 ms = ~37 s of Chroma RTT
just to build a user message whose response was already cached.

This module caches the FINAL ComplianceVerdict, keyed by the semantic
features of the pair (capability, last_cargo, cargo_type, …). Lookup
is O(1) hash, sub-millisecond, and lets the analyst skip RAG + LLM
entirely when the pair has been seen before.

Cache-key versioning
--------------------
The key includes a 8-char hash of `sanity_check.py`'s source code so the
cache auto-invalidates the day someone tweaks the rule predicates. We do
NOT include the analyst's prompt source — the cached verdict is the
post-sanity result, which is what the Strategist actually consumes; the
LLM's reasoning paragraph (separately cached in the LLM cache) is
rebuilt on a real LLM call if needed.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import threading
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
VERDICT_CACHE_PATH = BACKEND_DIR / ".llm_cache" / "verdict_cache.json"

_LOCK = threading.Lock()
_MEMO: dict[str, dict] | None = None
_DIRTY = False


def _sanity_version() -> str:
    """8-char hash of sanity_check.py — bumps when rule predicates change,
    auto-invalidating the cache so we never serve stale verdicts."""
    from app.agents import sanity_check
    src = inspect.getsource(sanity_check)
    return hashlib.sha256(src.encode()).hexdigest()[:8]


_SANITY_VERSION_CACHED: str | None = None


def _get_sanity_version() -> str:
    global _SANITY_VERSION_CACHED
    if _SANITY_VERSION_CACHED is None:
        _SANITY_VERSION_CACHED = _sanity_version()
    return _SANITY_VERSION_CACHED


def _semantic_key(truck: dict, load: dict) -> str:
    """Hash of the (truck, load) features that determine compliance.

    Identity-independent: two trucks with the same capability + last_cargo
    + wash certs produce the same key. Two loads with the same cargo
    type + forbidden_prior + temp range + logger requirement produce the
    same key. This means re-seeds with stable seed data keep cache hits.
    """
    wash_summary = sorted(
        f"{c.get('wash_type')}:{c.get('prior_cargo')}:{bool(c.get('is_currently_valid'))}"
        for c in (truck.get("wash_certificates") or [])
    )
    parts = [
        "v1",                                  # bump if key schema changes
        _get_sanity_version(),                 # auto-invalidate on rule change
        truck["temp_capability"],
        str(truck["last_cargo"] or "none"),
        str(bool(truck["has_pharma_logger"])),
        "|".join(wash_summary),
        load["cargo_type"],
        str(bool(load["requires_pharma_logger"])),
        str(load["forbidden_prior_cargo"] or "none"),
        f"{load['temp_min_celsius']:.1f}",
        f"{load['temp_max_celsius']:.1f}",
    ]
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:16]


def _load_cache() -> dict[str, dict]:
    global _MEMO
    with _LOCK:
        if _MEMO is not None:
            return _MEMO
        if VERDICT_CACHE_PATH.exists():
            try:
                _MEMO = json.loads(VERDICT_CACHE_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _MEMO = {}
        else:
            _MEMO = {}
        return _MEMO


def get_verdict(truck: dict, load: dict) -> dict | None:
    """Return a previously-cached ComplianceVerdict for this (truck, load)
    pair, or None on miss. Pure dict copy — caller can mutate freely."""
    cache = _load_cache()
    key = _semantic_key(truck, load)
    cached = cache.get(key)
    if cached is None:
        return None
    # Return a copy so the caller can mutate without polluting cache
    out = dict(cached)
    # Re-stamp the load_id to the actual load (semantic key is identity-free
    # so a load with the same cargo features but a different id maps here).
    out["load_id"] = load["id"]
    return out


def put_verdict(truck: dict, load: dict, verdict: dict) -> None:
    """Store the post-sanity verdict for this (truck, load) pair."""
    global _DIRTY
    cache = _load_cache()
    key = _semantic_key(truck, load)
    # Strip load_id so we don't accidentally key off id (semantic-key flow)
    payload = {k: v for k, v in verdict.items() if k != "load_id"}
    with _LOCK:
        cache[key] = payload
        _DIRTY = True


def flush_to_disk() -> int:
    """Persist any new entries. Called by analyst_fleet at end of batch.
    Returns the total number of cached entries."""
    global _DIRTY
    cache = _load_cache()
    with _LOCK:
        if not _DIRTY:
            return len(cache)
        VERDICT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = VERDICT_CACHE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, default=str), encoding="utf-8")
        tmp.replace(VERDICT_CACHE_PATH)
        _DIRTY = False
        return len(cache)


def stats() -> dict[str, Any]:
    """For diagnostics — current cache size + sanity version."""
    cache = _load_cache()
    return {
        "size": len(cache),
        "sanity_version": _get_sanity_version(),
        "path": str(VERDICT_CACHE_PATH),
    }


def clear() -> None:
    """Wipe the cache (e.g. after a known-good seed change)."""
    global _MEMO, _DIRTY
    with _LOCK:
        _MEMO = {}
        _DIRTY = False
    if VERDICT_CACHE_PATH.exists():
        VERDICT_CACHE_PATH.unlink()

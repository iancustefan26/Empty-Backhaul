"""Unit tests for the post-sanity verdict cache.

Verdict cache pins the FINAL ComplianceVerdict per semantic (truck, load)
features, letting `analyst_fleet()` skip both RAG and LLM on warm pairs.
These tests cover the contract:

  - same (capability, last_cargo, cargo_type, ...) → same key, cache hit
  - different load id but same features → cache hit (identity-free)
  - sanity_check.py code change → key changes, cache miss (auto-invalidate)
  - put / flush / clear round-trip preserves verdicts byte-equal
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents import verdict_cache as vc


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Each test gets its own cache file; in-memory state is wiped."""
    monkeypatch.setattr(vc, "VERDICT_CACHE_PATH", tmp_path / "verdict_cache.json")
    vc._MEMO = None
    vc._DIRTY = False
    vc._SANITY_VERSION_CACHED = None
    yield
    vc._MEMO = None
    vc._DIRTY = False
    vc._SANITY_VERSION_CACHED = None


def _truck(plate="CJ-101", capability="chilled", last_cargo="dairy",
           logger=False, wash=None):
    return {
        "id": hash(plate) % 1000,
        "plate_number": plate,
        "temp_capability": capability,
        "last_cargo": last_cargo,
        "has_pharma_logger": logger,
        "wash_certificates": wash or [],
    }


def _load(load_id=1, cargo="dairy", temp=(2.0, 7.0),
          forbidden="raw_meat,chemicals", needs_logger=False):
    return {
        "id": load_id,
        "cargo_type": cargo,
        "temp_min_celsius": temp[0],
        "temp_max_celsius": temp[1],
        "requires_pharma_logger": needs_logger,
        "forbidden_prior_cargo": forbidden,
    }


def _verdict(is_compliant=True, blockers=None, reasoning="ok"):
    return {
        "load_id": 99,                          # will be stripped by cache
        "is_compliant": is_compliant,
        "confidence": 0.9,
        "blockers": blockers or [],
        "warnings": [],
        "reasoning": reasoning,
        "cited_rule_ids": [],
        "cited_excerpts": [],
        "sanity_overrides": [],
    }


def test_put_then_get_returns_verdict():
    t, l = _truck(), _load()
    vc.put_verdict(t, l, _verdict(True, reasoning="dairy on chilled OK"))
    got = vc.get_verdict(t, l)
    assert got is not None
    assert got["is_compliant"] is True
    assert got["reasoning"] == "dairy on chilled OK"


def test_miss_returns_none():
    assert vc.get_verdict(_truck(), _load()) is None


def test_load_id_is_restamped_on_get():
    """The cache key is identity-free, so storing under load_id=99 and
    retrieving with load_id=42 must return a verdict tagged with 42."""
    t, l_stored = _truck(), _load(load_id=99)
    l_query = _load(load_id=42)        # same semantic features, different id
    vc.put_verdict(t, l_stored, _verdict(True))
    got = vc.get_verdict(t, l_query)
    assert got is not None
    assert got["load_id"] == 42


def test_semantic_key_ignores_id_but_distinguishes_features():
    """Two trucks with same capability + cargo features → same key.
    Different capability → different key."""
    t1 = _truck(plate="A", capability="chilled", last_cargo="dairy")
    t2 = _truck(plate="B", capability="chilled", last_cargo="dairy")
    t3 = _truck(plate="C", capability="frozen", last_cargo="dairy")
    l = _load()
    assert vc._semantic_key(t1, l) == vc._semantic_key(t2, l)
    assert vc._semantic_key(t1, l) != vc._semantic_key(t3, l)


def test_wash_certs_change_key():
    """A truck gaining a valid ANSVSA wash cert MUST change its key —
    otherwise a stale 'blocked' verdict would still be served after the
    truck was washed."""
    t_no_wash = _truck(plate="A", capability="chilled", last_cargo="raw_meat",
                        wash=[])
    t_with_wash = _truck(
        plate="A", capability="chilled", last_cargo="raw_meat",
        wash=[{"wash_type": "ansvsa_official", "prior_cargo": "raw_meat",
               "is_currently_valid": True}],
    )
    l = _load()
    assert vc._semantic_key(t_no_wash, l) != vc._semantic_key(t_with_wash, l)


def test_sanity_version_invalidates_cache():
    """Changing sanity_check.py source must change every key."""
    t, l = _truck(), _load()
    key_v1 = vc._semantic_key(t, l)

    # Pin a different sanity version
    vc._SANITY_VERSION_CACHED = "deadbeef"
    key_v2 = vc._semantic_key(t, l)

    assert key_v1 != key_v2


def test_flush_to_disk_roundtrips(tmp_path):
    t, l = _truck(), _load()
    vc.put_verdict(t, l, _verdict(True, reasoning="round-trip test"))
    n_entries = vc.flush_to_disk()
    assert n_entries == 1

    # Force fresh load from disk
    vc._MEMO = None
    got = vc.get_verdict(t, l)
    assert got is not None
    assert got["reasoning"] == "round-trip test"


def test_flush_is_noop_when_not_dirty():
    """Reading the cache should not re-write the disk file."""
    t, l = _truck(), _load()
    vc.put_verdict(t, l, _verdict(True))
    vc.flush_to_disk()
    mtime_1 = vc.VERDICT_CACHE_PATH.stat().st_mtime

    # No put → no flush → no file change
    _ = vc.get_verdict(t, l)
    vc.flush_to_disk()
    mtime_2 = vc.VERDICT_CACHE_PATH.stat().st_mtime

    assert mtime_1 == mtime_2


def test_clear_wipes_disk_and_memory():
    t, l = _truck(), _load()
    vc.put_verdict(t, l, _verdict(True))
    vc.flush_to_disk()
    assert vc.VERDICT_CACHE_PATH.exists()

    vc.clear()
    assert not vc.VERDICT_CACHE_PATH.exists()
    assert vc.get_verdict(t, l) is None


def test_stats_reports_size_and_version():
    t, l = _truck(), _load()
    vc.put_verdict(t, l, _verdict(True))
    s = vc.stats()
    assert s["size"] == 1
    assert isinstance(s["sanity_version"], str)
    assert len(s["sanity_version"]) == 8

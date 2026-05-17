"""Unit tests for the GeminiProvider hardening (retry / RPM / quota).

The provider is otherwise covered by integration tests; this file pins the
behaviours we cannot afford to break in a long-running experiment:

  - a transient 429 triggers exactly one retry, then succeeds
  - a non-transient exception is re-raised without retry
  - the daily-quota guard refuses further calls and raises GeminiQuotaError
  - cache hits short-circuit the API call and still log a cost-meter row
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make /backend importable when running this test file directly.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents import llm_provider as lp


@pytest.fixture(autouse=True)
def reset_throttle_state():
    """Each test starts with empty RPM + daily windows."""
    lp._recent_call_times.clear()
    lp._daily_call_times.clear()
    yield
    lp._recent_call_times.clear()
    lp._daily_call_times.clear()


class _FakeUsage:
    prompt_token_count = 100
    candidates_token_count = 50


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.usage_metadata = _FakeUsage()


class _FakeClient:
    """Minimal stand-in for `google.genai.Client` that fires a configurable
    sequence of errors/responses."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.models = self  # `client.models.generate_content(...)`

    def generate_content(self, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _install_fake_genai(monkeypatch, script):
    """Build a fake `google` package so `from google import genai` works."""
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    types_mod.ThinkingConfig = lambda **k: None
    types_mod.GenerateContentConfig = lambda **k: None
    fake = _FakeClient(script)
    genai_mod.Client = lambda api_key=None: fake
    google_mod.genai = genai_mod
    google_mod.genai.types = types_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return fake


def _patch_cache(monkeypatch, cached_value=None):
    """No-op cache so tests don't read/write the on-disk cache."""
    monkeypatch.setattr(lp.llm_cache, "get_cached", lambda *a, **k: cached_value)
    monkeypatch.setattr(lp.llm_cache, "put_cached", lambda *a, **k: None)


def _patch_cost_log(monkeypatch):
    """Capture cost-log rows in memory."""
    rows: list[dict] = []
    monkeypatch.setattr(lp, "_record_cost", lambda evt: rows.append(evt))
    return rows


class _Quota429(Exception):
    """Looks like a Gemini 429 — `_is_transient` should catch it via the
    'rate limit' substring in str(exc)."""
    def __str__(self):
        return "429 rate limit exceeded"


def test_transient_429_retries_once_then_succeeds(monkeypatch):
    _patch_cache(monkeypatch)
    rows = _patch_cost_log(monkeypatch)
    # Skip the actual sleep so the test is fast.
    monkeypatch.setattr(lp, "_retry_sleep", lambda attempt: 0)
    fake = _install_fake_genai(
        monkeypatch, [_Quota429(), _FakeResponse('{"ok": true}')],
    )

    p = lp.GeminiProvider(api_key="test")
    text, cached = p.evaluate("sys", "user")

    assert text == '{"ok": true}'
    assert cached is False
    assert fake.calls == 2, "should have made 2 attempts (1 fail + 1 success)"
    # Only the successful call writes a cost row (failed attempts don't unless
    # they were the final attempt).
    assert any(r["cache_hit"] is False and "error" not in r for r in rows)


def test_non_transient_error_raises_without_retry(monkeypatch):
    _patch_cache(monkeypatch)
    rows = _patch_cost_log(monkeypatch)
    monkeypatch.setattr(lp, "_retry_sleep", lambda attempt: 0)

    class _AuthError(Exception):
        def __str__(self):
            return "401 unauthorized — bad API key"

    fake = _install_fake_genai(monkeypatch, [_AuthError()])
    p = lp.GeminiProvider(api_key="test")

    with pytest.raises(_AuthError):
        p.evaluate("sys", "user")

    assert fake.calls == 1, "non-transient error should NOT retry"
    assert any("error" in r for r in rows)


def test_daily_quota_guard_aborts(monkeypatch):
    _patch_cache(monkeypatch)
    _patch_cost_log(monkeypatch)
    # Pre-fill the daily window so the guard trips immediately.
    monkeypatch.setattr(lp, "DEFAULT_DAILY_CAP", 5)
    now = datetime.now(timezone.utc)
    lp._daily_call_times.extend(now - timedelta(minutes=i) for i in range(5))

    _install_fake_genai(monkeypatch, [_FakeResponse("{}")])
    p = lp.GeminiProvider(api_key="test")

    with pytest.raises(lp.GeminiQuotaError):
        p.evaluate("sys", "user")


def test_cache_hit_short_circuits(monkeypatch):
    _patch_cache(monkeypatch, cached_value='{"hit": true}')
    rows = _patch_cost_log(monkeypatch)
    fake = _install_fake_genai(monkeypatch, [])
    p = lp.GeminiProvider(api_key="test")

    text, cached = p.evaluate("sys", "user")

    assert text == '{"hit": true}'
    assert cached is True
    assert fake.calls == 0
    assert rows and rows[-1]["cache_hit"] is True

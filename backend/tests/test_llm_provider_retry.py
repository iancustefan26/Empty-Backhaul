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
    # Pre-fill the daily window so the guard trips immediately. The cap
    # is read via the provider's `default_daily` class attribute (or
    # GEMINI_DAILY_CAP env override), so patch one of those.
    monkeypatch.setattr(lp.GeminiProvider, "default_daily", 5)
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


# ---------------------------------------------------------------------------
# VertexAIProvider — reuses the same retry/RPM/cost-meter loop with a
# different client constructor and different default throttle.
# ---------------------------------------------------------------------------

def test_vertex_provider_uses_vertexai_client(monkeypatch):
    """VertexAIProvider must construct the genai.Client with vertexai=True."""
    captured_kwargs = {}

    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    types_mod.ThinkingConfig = lambda **k: None
    types_mod.GenerateContentConfig = lambda **k: None

    def _client_ctor(**kwargs):
        captured_kwargs.update(kwargs)
        return _FakeClient([_FakeResponse('{"ok": true}')])

    genai_mod.Client = _client_ctor
    google_mod.genai = genai_mod
    google_mod.genai.types = types_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)

    _patch_cache(monkeypatch)
    _patch_cost_log(monkeypatch)

    p = lp.VertexAIProvider(api_key="AQ.test")
    p.evaluate("sys", "user")

    assert captured_kwargs.get("vertexai") is True, (
        "VertexAIProvider must pass vertexai=True; got " + repr(captured_kwargs)
    )
    assert captured_kwargs.get("api_key") == "AQ.test"


def test_vertex_provider_uses_higher_throttle_defaults():
    """Vertex defaults must allow much higher throughput than AI Studio."""
    gemini = lp.GeminiProvider(api_key="AIza-test")
    vertex = lp.VertexAIProvider(api_key="AQ.test")

    assert vertex.default_rpm > gemini.default_rpm, (
        f"Vertex RPM ({vertex.default_rpm}) should exceed Gemini RPM "
        f"({gemini.default_rpm})"
    )
    assert vertex.default_daily > gemini.default_daily
    # Sanity: Vertex throughput should be at least 6× the AI Studio default
    # (60 vs 9 today, ratio of ~6.7) — protects us against accidental
    # regressions if defaults drift.
    assert vertex.default_rpm >= gemini.default_rpm * 6


def test_vertex_provider_inherits_retry_path(monkeypatch):
    """VertexAIProvider should retry on transient errors exactly like
    GeminiProvider (the retry loop is inherited)."""
    _patch_cache(monkeypatch)
    rows = _patch_cost_log(monkeypatch)
    monkeypatch.setattr(lp, "_retry_sleep", lambda attempt: 0)
    fake = _install_fake_genai(
        monkeypatch, [_Quota429(), _FakeResponse('{"ok": true}')],
    )
    # _install_fake_genai installed an AI Studio fake; override to make Vertex's
    # _make_client return the same fake regardless of kwargs.
    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", lambda **kw: fake)

    p = lp.VertexAIProvider(api_key="AQ.test")
    text, cached = p.evaluate("sys", "user")

    assert text == '{"ok": true}'
    assert cached is False
    assert fake.calls == 2, "vertex must retry once on transient 429"


def test_factory_prefers_vertex_when_key_set(monkeypatch):
    """get_provider() with both keys set should pick Vertex."""
    from app.core.config import Settings
    monkeypatch.setenv("GCP_PROJECT", "")          # disable ADC mode so we
    monkeypatch.setenv("VERTEX_AI_API_KEY", "AQ.test-vertex")  # test Express
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-gemini")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    # bust the lru_cache
    import app.core.config as cfg
    cfg.get_settings.cache_clear()

    p = lp.get_provider()
    assert type(p).__name__ == "VertexAIProvider"
    assert p.model.startswith("gemini-")
    assert p.auth_mode == "express"


def test_factory_routes_aq_prefixed_gemini_key_to_vertex(monkeypatch):
    """Back-compat: an AQ.* value in GEMINI_API_KEY is actually a Vertex
    Express Mode key — the factory should route it through Vertex."""
    # Empty-string env vars override any values in backend/.env (pydantic
    # reads both, env wins). Without this, GCP_PROJECT from .env would
    # cause the factory to pick ADC mode instead of Express.
    monkeypatch.setenv("VERTEX_AI_API_KEY", "")
    monkeypatch.setenv("GCP_PROJECT", "")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.legacy-vertex-key")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    import app.core.config as cfg
    cfg.get_settings.cache_clear()

    p = lp.get_provider()
    assert type(p).__name__ == "VertexAIProvider"
    assert p.auth_mode == "express"


# ---------------------------------------------------------------------------
# VertexAIProvider — ADC mode (project + location, no API key)
# ---------------------------------------------------------------------------

def test_vertex_adc_mode_constructs_client_with_project_and_location(monkeypatch):
    """ADC mode: project + location → genai.Client(vertexai=True,
    project=..., location=...), no api_key passed."""
    captured = {}

    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    types_mod.ThinkingConfig = lambda **k: None
    types_mod.GenerateContentConfig = lambda **k: None

    def _client_ctor(**kwargs):
        captured.update(kwargs)
        return _FakeClient([_FakeResponse('{"ok": true}')])

    genai_mod.Client = _client_ctor
    google_mod.genai = genai_mod
    google_mod.genai.types = types_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)

    _patch_cache(monkeypatch)
    _patch_cost_log(monkeypatch)

    p = lp.VertexAIProvider(project="my-gcp-project", location="europe-west1")
    assert p.auth_mode == "adc"
    p.evaluate("sys", "user")

    assert captured.get("vertexai") is True
    assert captured.get("project") == "my-gcp-project"
    assert captured.get("location") == "europe-west1"
    assert "api_key" not in captured, \
        "ADC mode must NOT pass api_key (would force Express Mode)"


def test_vertex_provider_requires_api_key_or_project():
    with pytest.raises(ValueError, match="api_key.*OR.*project"):
        lp.VertexAIProvider()


def test_factory_prefers_adc_over_api_key(monkeypatch):
    """get_provider() with BOTH GCP_PROJECT and VERTEX_AI_API_KEY should
    pick ADC because it has higher quotas."""
    monkeypatch.setenv("GCP_PROJECT", "poetic-emblem-490411-p0")
    monkeypatch.setenv("VERTEX_AI_API_KEY", "AQ.unused-because-adc-wins")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    import app.core.config as cfg
    cfg.get_settings.cache_clear()

    p = lp.get_provider()
    assert type(p).__name__ == "VertexAIProvider"
    assert p.auth_mode == "adc"


def test_factory_falls_back_to_express_when_no_project(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "")          # override .env
    monkeypatch.setenv("VERTEX_AI_API_KEY", "AQ.express-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    import app.core.config as cfg
    cfg.get_settings.cache_clear()

    p = lp.get_provider()
    assert type(p).__name__ == "VertexAIProvider"
    assert p.auth_mode == "express"

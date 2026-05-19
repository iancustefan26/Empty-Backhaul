"""LLM provider abstraction for the Analyst.

The Analyst used to call Anthropic Claude directly. This module wraps that
behind a tiny `LLMProvider` protocol so the same agent code works against:

  - Gemini  (Google AI Studio free tier, default when GEMINI_API_KEY is set)
  - Claude  (Anthropic, when ANTHROPIC_API_KEY is set)
  - Mock    (deterministic fallback, used when no key is available or when
             `--mock-llm` is passed in the CLI)

Selection is driven by `LLM_PROVIDER` (`auto` | `gemini` | `anthropic` |
`mock`). In `auto` mode (the default) we prefer Gemini, then Anthropic, then
Mock — matching the user's free-tier reality.

Both real providers cap output at 512 tokens and request JSON-only responses
to keep per-call costs predictable.

## Gemini hardening (v2)

For the per-agent experiment suite we need to call the live Gemini API
hundreds of times in a row without:

  * crashing on a 429 (free tier 10 RPM, 250 RPD)
  * silently burning the daily quota on retries
  * losing per-call telemetry (token spend, latency, cache hits)

`GeminiProvider` is wrapped with:

  1. Exponential-backoff retry on transient errors (429 / 5xx / SDK
     `ResourceExhausted`) with capped jitter.
  2. Module-level soft RPM throttle (`GEMINI_RPM_CAP`, default 9 to stay
     one below the documented 10 RPM ceiling).
  3. A JSONL cost log (`backend/.llm_cache/cost_log.jsonl`) recording
     (input_tokens, output_tokens, model, cache_hit, latency_ms) per
     call. The experiment runner aggregates the log into run_summary.json.
  4. A daily-quota guard that aborts the run with a clear message if we
     have made more than `GEMINI_DAILY_CAP` fresh API calls in the
     rolling 24 h window — better to fail fast than burn on 429s.

The hardening is opt-in via env vars; default behaviour matches the old
provider so unit tests and demos are unchanged.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from app.agents import llm_cache
from app.core.config import get_settings

GEMINI_MODEL_ENV = "GEMINI_MODEL"
VERTEX_MODEL_ENV = "VERTEX_MODEL"
ANTHROPIC_MODEL_ENV = "ANTHROPIC_MODEL"

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"   # same model, different routing
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"

# Output budget per Analyst call. The verdict JSON is ~300-600 tokens of
# visible output; we set 2048 to leave headroom and to absorb model "thinking"
# tokens (Gemini 2.5 Flash counts thinking against this same budget). On
# Gemini Flash this caps a single call at well under $0.01.
MAX_OUTPUT_TOKENS = 2048


# ---------------------------------------------------------------------------
# Hardening (v2): rate-limit, retry/backoff, cost log, daily-quota guard
# ---------------------------------------------------------------------------

# Free AI-Studio tier is 10 RPM, 250 RPD; default to 9 / 225 so a slow
# clock or burst can't push us over. Tunable via env so paid-tier users
# can lift it without code change.
#
# Vertex AI Express Mode (tier 1, Gemini 2.5 Flash) is ~500 RPM with NO
# documented daily cap — we default Vertex to 60 RPM / 10 000 RPD so an
# interactive plan request finishes in seconds, not hours, while still
# keeping plenty of headroom. Override with VERTEX_RPM_CAP / VERTEX_DAILY_CAP.
DEFAULT_RPM_CAP = int(os.environ.get("GEMINI_RPM_CAP", "9"))
DEFAULT_DAILY_CAP = int(os.environ.get("GEMINI_DAILY_CAP", "225"))
DEFAULT_VERTEX_RPM_CAP = int(os.environ.get("VERTEX_RPM_CAP", "60"))
DEFAULT_VERTEX_DAILY_CAP = int(os.environ.get("VERTEX_DAILY_CAP", "10000"))
# Retry policy on 429 / 5xx / ResourceExhausted.
RETRY_MAX_ATTEMPTS = int(os.environ.get("GEMINI_RETRY_ATTEMPTS", "4"))
RETRY_BASE_DELAY_S = float(os.environ.get("GEMINI_RETRY_BASE_DELAY_S", "4.0"))
RETRY_CAP_DELAY_S = float(os.environ.get("GEMINI_RETRY_CAP_DELAY_S", "60.0"))

COST_LOG_PATH = Path(__file__).resolve().parents[2] / ".llm_cache" / "cost_log.jsonl"

_rate_lock = threading.Lock()
# Sliding window of timestamps of the last `DEFAULT_RPM_CAP` fresh calls.
_recent_call_times: list[float] = []
# Sliding 24 h window for the daily quota guard.
_daily_call_times: list[datetime] = []


class GeminiQuotaError(RuntimeError):
    """Raised when the daily-quota guard refuses to make another call."""


def _record_cost(event: dict) -> None:
    """Append a single cost-log line. Best-effort — never raises."""
    try:
        COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with COST_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


def _enforce_rpm(rpm_cap: int) -> None:
    """Sleep until making one more call would stay within `rpm_cap`."""
    with _rate_lock:
        now = time.monotonic()
        cutoff = now - 60.0
        # Keep only the last 60 s worth of timestamps.
        del _recent_call_times[:len(_recent_call_times) - rpm_cap]
        while _recent_call_times and _recent_call_times[0] < cutoff:
            _recent_call_times.pop(0)
        if len(_recent_call_times) >= rpm_cap:
            sleep_for = 60.0 - (now - _recent_call_times[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
        _recent_call_times.append(time.monotonic())


def _enforce_daily_cap(daily_cap: int) -> None:
    """Raise GeminiQuotaError if a call would exceed `daily_cap` in 24 h."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with _rate_lock:
        while _daily_call_times and _daily_call_times[0] < cutoff:
            _daily_call_times.pop(0)
        if len(_daily_call_times) >= daily_cap:
            oldest = _daily_call_times[0]
            wait_h = ((oldest + timedelta(hours=24)) - datetime.now(timezone.utc)).total_seconds() / 3600
            raise GeminiQuotaError(
                f"Gemini daily-quota guard tripped at {daily_cap} calls in the rolling 24 h "
                f"window. Wait ~{wait_h:.1f} h or raise GEMINI_DAILY_CAP."
            )
        _daily_call_times.append(datetime.now(timezone.utc))


def _is_transient(exc: BaseException) -> bool:
    """True if `exc` looks like a 429 / 5xx / ResourceExhausted from Gemini."""
    name = type(exc).__name__
    if name in {"ResourceExhausted", "ServiceUnavailable", "DeadlineExceeded",
                "InternalServerError", "Aborted", "Unavailable"}:
        return True
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "quota" in msg:
        return True
    if "500" in msg or "503" in msg or "internal" in msg or "unavailable" in msg:
        return True
    return False


def _retry_sleep(attempt: int) -> float:
    """Exponential backoff with ±25 % jitter, capped at RETRY_CAP_DELAY_S."""
    base = min(RETRY_CAP_DELAY_S, RETRY_BASE_DELAY_S * (2 ** (attempt - 1)))
    jitter = base * 0.25 * (random.random() * 2 - 1)
    return max(0.1, base + jitter)


class LLMProvider(Protocol):
    name: str
    model: str

    def evaluate(self, system: str, user: str) -> tuple[str, bool]:
        """Return (raw model response string, cache_hit flag).

        Response is expected to be JSON. `cache_hit` is True when the response
        came from the on-disk cache (no API call billed).
        """
        ...


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class GeminiProvider:
    """Google AI Studio (a.k.a. generativelanguage.googleapis.com) provider.

    Tier defaults: 9 RPM, 225 RPD (free tier — 1 below the 10 RPM / 250
    RPD documented ceiling).  Override via GEMINI_RPM_CAP / GEMINI_DAILY_CAP.
    """
    name = "gemini"
    default_rpm = DEFAULT_RPM_CAP
    default_daily = DEFAULT_DAILY_CAP
    rpm_env_var = "GEMINI_RPM_CAP"
    daily_env_var = "GEMINI_DAILY_CAP"
    model_env_var = GEMINI_MODEL_ENV
    default_model = DEFAULT_GEMINI_MODEL

    def __init__(self, api_key: str, model: str | None = None) -> None:
        if not api_key:
            raise ValueError(f"{type(self).__name__} requires a non-empty API key")
        self._api_key = api_key
        self.model = model or os.environ.get(self.model_env_var, self.default_model)

    # ---- subclasses override one of these two methods ----

    def _make_client(self):
        """Build the google.genai client. Subclasses override for Vertex."""
        from google import genai  # type: ignore[import-not-found]
        return genai.Client(api_key=self._api_key)

    def _rpm_cap(self) -> int:
        # Resolution order: process env > .env (via Settings) > class default.
        env_val = os.environ.get(self.rpm_env_var)
        if env_val is not None:
            return int(env_val)
        settings_attr = self.rpm_env_var.lower()
        settings_val = getattr(get_settings(), settings_attr, None)
        if settings_val is not None:
            return int(settings_val)
        return self.default_rpm

    def _daily_cap(self) -> int:
        env_val = os.environ.get(self.daily_env_var)
        if env_val is not None:
            return int(env_val)
        settings_attr = self.daily_env_var.lower()
        settings_val = getattr(get_settings(), settings_attr, None)
        if settings_val is not None:
            return int(settings_val)
        return self.default_daily

    # ---- shared retry / throttle / cost-meter loop ----

    def evaluate(self, system: str, user: str) -> tuple[str, bool]:
        cached = llm_cache.get_cached(self.name, self.model, system, user)
        if cached is not None:
            _record_cost({
                "ts": datetime.now(timezone.utc).isoformat(),
                "provider": self.name, "model": self.model,
                "cache_hit": True, "input_tokens": 0, "output_tokens": 0,
                "latency_ms": 0, "attempts": 0,
            })
            return cached, True

        from google.genai import types  # type: ignore[import-not-found]

        client = self._make_client()
        thinking_config = None
        if self.model.startswith("gemini-2.5"):
            try:
                thinking_config = types.ThinkingConfig(thinking_budget=0)
            except (AttributeError, TypeError):
                thinking_config = None

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.1,
            thinking_config=thinking_config,
        )

        rpm_cap = self._rpm_cap()
        daily_cap = self._daily_cap()

        last_exc: BaseException | None = None
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                _enforce_daily_cap(daily_cap)
                _enforce_rpm(rpm_cap)
                t0 = time.perf_counter()
                response = client.models.generate_content(
                    model=self.model, contents=user, config=config,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                text = (response.text or "").strip()
                in_tok = out_tok = 0
                usage = getattr(response, "usage_metadata", None)
                if usage is not None:
                    in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
                    out_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
                _record_cost({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "provider": self.name, "model": self.model,
                    "cache_hit": False, "input_tokens": in_tok,
                    "output_tokens": out_tok, "latency_ms": latency_ms,
                    "attempts": attempt,
                })
                llm_cache.put_cached(self.name, self.model, system, user, text)
                return text, False
            except GeminiQuotaError:
                raise
            except BaseException as exc:
                last_exc = exc
                if not _is_transient(exc) or attempt == RETRY_MAX_ATTEMPTS:
                    _record_cost({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "provider": self.name, "model": self.model,
                        "cache_hit": False, "input_tokens": 0,
                        "output_tokens": 0, "latency_ms": 0,
                        "attempts": attempt, "error": type(exc).__name__,
                        "error_msg": str(exc)[:200],
                    })
                    raise
                time.sleep(_retry_sleep(attempt))

        # Defensive — loop above either returns or raises.
        raise RuntimeError(f"{type(self).__name__}.evaluate exhausted retries: {last_exc!r}")


# ---------------------------------------------------------------------------
# Vertex AI (Express Mode — same SDK, different routing)
# ---------------------------------------------------------------------------

class VertexAIProvider(GeminiProvider):
    """Google Cloud Vertex AI provider using Express Mode (API key, no
    service-account JSON, no project/location config required).

    Same `google-genai` SDK as `GeminiProvider`; only the client is built
    with `vertexai=True` so requests go through Vertex's serving stack
    instead of AI Studio. Result: same model (`gemini-2.5-flash`), same
    pricing per token, but with **dramatically higher rate limits** — 500
    RPM and no daily cap on Express Mode tier 1. We default the throttle
    to 60 RPM (1 call/sec) so an interactive plan request that needed
    750 fresh LLM calls finishes in ~13 minutes instead of ~84 minutes.

    Charges count against the GCP project's billing / free trial credit.

    Activated when VERTEX_AI_API_KEY (or, for back-compat, an AQ.*-prefixed
    GEMINI_API_KEY) is present. See `get_provider()`.
    """
    name = "vertex"
    default_rpm = DEFAULT_VERTEX_RPM_CAP
    default_daily = DEFAULT_VERTEX_DAILY_CAP
    rpm_env_var = "VERTEX_RPM_CAP"
    daily_env_var = "VERTEX_DAILY_CAP"
    model_env_var = VERTEX_MODEL_ENV
    default_model = DEFAULT_VERTEX_MODEL

    def _make_client(self):
        from google import genai  # type: ignore[import-not-found]
        return genai.Client(vertexai=True, api_key=self._api_key)


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------

class AnthropicProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        if not api_key:
            raise ValueError("AnthropicProvider requires a non-empty API key")
        self._api_key = api_key

        import os
        self.model = model or os.environ.get(ANTHROPIC_MODEL_ENV, DEFAULT_ANTHROPIC_MODEL)

    def evaluate(self, system: str, user: str) -> tuple[str, bool]:
        cached = llm_cache.get_cached(self.name, self.model, system, user)
        if cached is not None:
            return cached, True

        from anthropic import Anthropic  # lazy import

        client = Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = msg.content[0].text
        llm_cache.put_cached(self.name, self.model, system, user, text)
        return text, False


# ---------------------------------------------------------------------------
# Mock — sentinel only. The Analyst already has a deterministic mock evaluator
# (`_evaluate_mock`) that does not need an LLM at all. The factory returns this
# sentinel so callers can detect "no real provider available" with a single
# isinstance check.
# ---------------------------------------------------------------------------

class MockProvider:
    name = "mock"
    model = "deterministic"

    def evaluate(self, system: str, user: str) -> tuple[str, bool]:  # pragma: no cover
        raise RuntimeError(
            "MockProvider.evaluate should never be called — the Analyst's "
            "deterministic path bypasses the LLM entirely."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider(force: str | None = None) -> LLMProvider:
    """Pick a provider based on `LLM_PROVIDER` and which API keys are set.

    `force` overrides the env (used by tests). Values: `vertex`, `gemini`,
    `anthropic`, `mock`, `auto`.

    Resolution order under `auto`:
      1. Vertex AI (if VERTEX_AI_API_KEY is set) — preferred because it's
         faster (60+ RPM vs 9 RPM on AI Studio) and uses GCP billing /
         free-trial credit
      2. AI Studio Gemini (if GEMINI_API_KEY is set and looks like an
         AI Studio key — starts with "AIza"). If GEMINI_API_KEY is set
         but its value looks like a Vertex key (starts with "AQ."), we
         treat it as a Vertex key for back-compat.
      3. Anthropic
      4. Mock
    """
    settings = get_settings()
    choice = (force or settings.llm_provider or "auto").lower()

    if choice == "vertex":
        return VertexAIProvider(settings.vertex_ai_api_key or settings.gemini_api_key)
    if choice == "gemini":
        return GeminiProvider(settings.gemini_api_key)
    if choice == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key)
    if choice == "mock":
        return MockProvider()
    if choice != "auto":
        raise ValueError(f"unknown LLM_PROVIDER={choice!r}")

    # auto resolution.
    if settings.vertex_ai_api_key:
        return VertexAIProvider(settings.vertex_ai_api_key)
    if settings.gemini_api_key:
        # Back-compat: an AQ.*-prefixed value in GEMINI_API_KEY is actually
        # a Vertex AI Express Mode key. Route it through Vertex.
        if settings.gemini_api_key.startswith("AQ."):
            return VertexAIProvider(settings.gemini_api_key)
        return GeminiProvider(settings.gemini_api_key)
    if settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key)
    return MockProvider()

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
ANTHROPIC_MODEL_ENV = "ANTHROPIC_MODEL"

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"

# Output budget per Analyst call. The verdict JSON is ~300-600 tokens of
# visible output; we set 2048 to leave headroom and to absorb model "thinking"
# tokens (Gemini 2.5 Flash counts thinking against this same budget). On
# Gemini Flash this caps a single call at well under $0.01.
MAX_OUTPUT_TOKENS = 2048


# ---------------------------------------------------------------------------
# Hardening (v2): rate-limit, retry/backoff, cost log, daily-quota guard
# ---------------------------------------------------------------------------

# Free tier is 10 RPM; default to 9 so a slow clock or burst can't push us
# over. Tunable via env so paid-tier users can lift it without code change.
DEFAULT_RPM_CAP = int(os.environ.get("GEMINI_RPM_CAP", "9"))
# 250 RPD on the free tier. We keep a 10 % safety margin (225) so a half-day
# resume doesn't trip the wall.
DEFAULT_DAILY_CAP = int(os.environ.get("GEMINI_DAILY_CAP", "225"))
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
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        if not api_key:
            raise ValueError("GeminiProvider requires a non-empty API key")
        self._api_key = api_key

        import os
        self.model = model or os.environ.get(GEMINI_MODEL_ENV, DEFAULT_GEMINI_MODEL)

    def evaluate(self, system: str, user: str) -> tuple[str, bool]:
        cached = llm_cache.get_cached(self.name, self.model, system, user)
        if cached is not None:
            # Cost log: cache hits are free but we still want to count them.
            _record_cost({
                "ts": datetime.now(timezone.utc).isoformat(),
                "provider": self.name, "model": self.model,
                "cache_hit": True, "input_tokens": 0, "output_tokens": 0,
                "latency_ms": 0, "attempts": 0,
            })
            return cached, True

        # Lazy import so mock-only / anthropic-only runs don't need the SDK.
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]

        client = genai.Client(api_key=self._api_key)
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

        rpm_cap = DEFAULT_RPM_CAP
        daily_cap = DEFAULT_DAILY_CAP

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
        raise RuntimeError(f"GeminiProvider.evaluate exhausted retries: {last_exc!r}")


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

    `force` overrides the env (used by tests). Values: `gemini`, `anthropic`,
    `mock`, `auto`.
    """
    settings = get_settings()
    choice = (force or settings.llm_provider or "auto").lower()

    if choice == "gemini":
        return GeminiProvider(settings.gemini_api_key)
    if choice == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key)
    if choice == "mock":
        return MockProvider()
    if choice != "auto":
        raise ValueError(f"unknown LLM_PROVIDER={choice!r}")

    # auto: prefer Gemini (free tier), then Anthropic, then mock.
    if settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key)
    if settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key)
    return MockProvider()

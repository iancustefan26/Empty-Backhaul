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
"""
from __future__ import annotations

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
            return cached, True

        # Lazy import so mock-only / anthropic-only runs don't need the SDK.
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]

        client = genai.Client(api_key=self._api_key)
        # Disable Gemini 2.5 "thinking" for the Analyst — we need fast,
        # deterministic JSON, not chain-of-thought reasoning that consumes
        # the output budget.
        thinking_config = None
        if self.model.startswith("gemini-2.5"):
            try:
                thinking_config = types.ThinkingConfig(thinking_budget=0)
            except (AttributeError, TypeError):
                thinking_config = None  # older SDKs without ThinkingConfig
        response = client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.1,
                thinking_config=thinking_config,
            ),
        )
        text = (response.text or "").strip()
        llm_cache.put_cached(self.name, self.model, system, user, text)
        return text, False


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

"""Shared utilities for the per-agent experiment suite (experiments_v2).

`hydrate()` keeps the v1 contract — one Sentry + Analyst-fleet pass on the
seeded fleet — so PR4's exp_a..exp_d still work unchanged.

v2 additions:

  - `EXP_V2_DIR`        : output directory for the new experiments
  - `assert_invariants` : truthfulness gate; raises on any False predicate
    with a clear pointer to the predicate's source so the operator can
    investigate the logic instead of trusting a non-sense number
  - `provenance_block`  : git SHA + seed timestamp + Gemini model used
  - `cost_meter_summary`: parse the JSONL cost log and return totals
    (calls, tokens, EUR cost on Flash pricing, wall time)
  - `current_git_sha`   : short SHA of HEAD; tolerates missing git
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.fleet_workflow import analyst_fleet, sentry_fleet  # noqa: E402
from app.agents.llm_provider import COST_LOG_PATH  # noqa: E402

EXP_DIR = BACKEND_DIR / "docs" / "experiments"
EXP_V2_DIR = BACKEND_DIR / "docs" / "experiments_v2"
FIG_V2_DIR = BACKEND_DIR / "docs" / "figures" / "experiments_v2"

# Gemini 2.5 Flash pricing — Sept 2025 public list price.
# Source: https://ai.google.dev/pricing
GEMINI_FLASH_INPUT_USD_PER_M = 0.30
GEMINI_FLASH_OUTPUT_USD_PER_M = 2.50
USD_TO_EUR = 0.92  # rough; thesis can update without code change


def hydrate(
    *,
    include_broker: bool = True,
    fleet_size: int = 25,
    use_mock_llm: bool = True,
) -> dict:
    """Single Sentry + Analyst-fleet pass. Returns a dict with `vans`,
    `loads`, `compliance`, `sentry_log`, `analyst_log`.

    Pass `use_mock_llm=False` to enrich verdicts with live Gemini (with
    the cache + sanity-layer in front).
    """
    sentry = sentry_fleet(include_broker=include_broker, fleet_size=fleet_size)
    if "error" in sentry:
        sys.exit(f"Sentry error: {sentry['error']}")
    vans = sentry["fleet"]
    loads = sentry["available_loads"]
    compliance, analyst_log = analyst_fleet(vans, loads, use_mock_llm=use_mock_llm)
    return {
        "vans": vans, "loads": loads, "compliance": compliance,
        "sentry_log": sentry["sentry_log"], "analyst_log": analyst_log,
    }


def write_json(experiment_id: str, payload: dict) -> Path:
    """Write to docs/experiments/ (legacy PR4 path)."""
    out = EXP_DIR / f"{experiment_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    return out


def write_v2_json(experiment_id: str, payload: dict) -> Path:
    out = EXP_V2_DIR / f"{experiment_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    return out


# ---------------------------------------------------------------------------
# Truthfulness gate
# ---------------------------------------------------------------------------

class InvariantFailure(SystemExit):
    """Raised by `assert_invariants` to abort an experiment script with a
    non-zero exit code and a clear pointer to the failing predicate."""


def assert_invariants(checks: list[tuple[bool, str, str]]) -> None:
    """Assert a list of (passed, label, where_to_look) triples.

    On any False, print every failed check (not just the first) so the
    operator can see all issues at once, then exit with code 1. The
    `where_to_look` string should point at the source-file + symbol that
    likely caused the failure — that's the "investigate the logic" hint.
    """
    failed = [(label, where) for ok, label, where in checks if not ok]
    if not failed:
        return
    print("\n=== INVARIANT FAILURES ===", file=sys.stderr)
    for label, where in failed:
        print(f"  ✗ {label}", file=sys.stderr)
        print(f"      investigate: {where}", file=sys.stderr)
    print("==========================\n", file=sys.stderr)
    raise InvariantFailure(1)


# ---------------------------------------------------------------------------
# Provenance + cost meter
# ---------------------------------------------------------------------------

def current_git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BACKEND_DIR, stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def provenance_block(*, mode: str, model: str | None) -> dict:
    """Standard provenance dict embedded in every v2 experiment JSON."""
    return {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": current_git_sha(),
        "mode": mode,           # "mock" | "gemini"
        "model": model,         # e.g. "gemini-2.5-flash" or None for mock
        "seed_fleet_size": int(os.environ.get("EXP_FLEET_SIZE", "25")),
        "seed_load_pool_size": int(os.environ.get("EXP_LOAD_POOL_SIZE", "100")),
    }


def cost_meter_summary(*, since: datetime | None = None) -> dict:
    """Aggregate the JSONL cost log produced by GeminiProvider.

    `since` lets the runner zero out the meter at start-of-run so the
    per-experiment cost is attributable, not a lifetime total.
    """
    if not COST_LOG_PATH.exists():
        return {"calls": 0, "cache_hits": 0, "input_tokens": 0,
                "output_tokens": 0, "cost_usd": 0.0, "cost_eur": 0.0,
                "latency_ms": 0, "errors": 0}
    calls = cache_hits = errors = 0
    in_tok = out_tok = latency_ms = 0
    for line in COST_LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if since is not None:
            try:
                ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < since:
                continue
        if row.get("cache_hit"):
            cache_hits += 1
            continue
        if "error" in row:
            errors += 1
            continue
        calls += 1
        in_tok += int(row.get("input_tokens") or 0)
        out_tok += int(row.get("output_tokens") or 0)
        latency_ms += int(row.get("latency_ms") or 0)
    cost_usd = (
        in_tok / 1_000_000 * GEMINI_FLASH_INPUT_USD_PER_M
        + out_tok / 1_000_000 * GEMINI_FLASH_OUTPUT_USD_PER_M
    )
    return {
        "calls": calls,
        "cache_hits": cache_hits,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost_usd, 4),
        "cost_eur": round(cost_usd * USD_TO_EUR, 4),
        "latency_ms": latency_ms,
        "errors": errors,
    }

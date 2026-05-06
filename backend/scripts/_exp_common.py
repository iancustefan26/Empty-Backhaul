"""Shared utilities for the four PR4 experiments.

Each experiment compares a baseline (representing 'life before our system')
against the treatment (the route planner) on the same fleet + load pool.
This module hoists the common setup (Sentry hydration, Analyst-fleet, JSON
output path) so the experiment scripts stay focused on their hypothesis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.fleet_workflow import analyst_fleet, sentry_fleet  # noqa: E402

EXP_DIR = BACKEND_DIR / "docs" / "experiments"


def hydrate(*, include_broker: bool = True, fleet_size: int = 15) -> dict:
    """Single Sentry + Analyst-fleet pass. Returns a dict with `vans`,
    `loads`, `compliance`, `sentry_log`, `analyst_log`."""
    sentry = sentry_fleet(include_broker=include_broker, fleet_size=fleet_size)
    if "error" in sentry:
        sys.exit(f"Sentry error: {sentry['error']}")
    vans = sentry["fleet"]
    loads = sentry["available_loads"]
    compliance, analyst_log = analyst_fleet(vans, loads, use_mock_llm=True)
    return {
        "vans": vans, "loads": loads, "compliance": compliance,
        "sentry_log": sentry["sentry_log"], "analyst_log": analyst_log,
    }


def write_json(experiment_id: str, payload: dict) -> Path:
    out = EXP_DIR / f"{experiment_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    return out

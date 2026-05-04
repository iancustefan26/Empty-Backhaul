"""CI gate: run the ground-truth eval in mock mode and require ≥95% accuracy.

Mock mode IS the deterministic hard-rules layer, so anything below 100% means
either the ground truth is mislabelled or the predicates have drifted. We set
the bar at 95% to leave room for one row of judgement-call labels (e.g. a
borderline blocker-id substring) without forcing immediate flakiness.
"""
from __future__ import annotations

import os

import pytest

# Skip cleanly when there's no DB configured (e.g. PR-only CI without secrets).
pytestmark = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DATABASE_URL"),
    reason="SUPABASE_DATABASE_URL not set; skipping eval smoke (needs DB).",
)


def test_eval_mock_accuracy_above_threshold():
    from scripts.run_eval import evaluate

    summary = evaluate(provider="mock", json_only=True)
    accuracy = summary["accuracy"]
    assert accuracy >= 0.95, (
        f"Mock-mode eval dropped to {accuracy:.1%} (threshold 95%). "
        f"Mismatches: {summary['mismatches']}"
    )
    assert summary["errors"] == 0, f"Eval rows errored: {summary}"

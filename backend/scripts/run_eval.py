"""CLI: evaluate the Analyst against the ground-truth dataset.

    python -m scripts.run_eval                          # mock provider, fast, free
    python -m scripts.run_eval --provider gemini        # live, ~$0 on free tier
    python -m scripts.run_eval --json > eval.json       # machine-readable for the thesis appendix

Reads `tests/ground_truth.yaml`, groups cases by truck plate (so the full
Sentry → Analyst pipeline runs once per truck), compares the verdicts to the
expected labels, and prints a precision/recall report with a confusion matrix
and the worst mismatches.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import yaml  # noqa: E402

from app.agents.workflow import run_match_workflow  # noqa: E402
from sqlalchemy import text  # noqa: E402
from app.core.database import engine  # noqa: E402

GROUND_TRUTH_PATH = BACKEND_DIR / "tests" / "ground_truth.yaml"


def load_cases(path: Path = GROUND_TRUTH_PATH) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["cases"]


def resolve_truck_id(plate: str) -> int | None:
    if engine is None:
        raise RuntimeError("Database engine not configured (SUPABASE_DATABASE_URL missing).")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM trucks WHERE plate_number = :p"), {"p": plate}).first()
        return row[0] if row else None


def evaluate(provider: str, json_only: bool = False) -> dict:
    cases = load_cases()
    by_truck: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by_truck[c["truck_plate"]].append(c)

    use_mock = provider == "mock"
    # Force the chosen provider via env so the existing factory path picks it up.
    if not use_mock:
        os.environ["LLM_PROVIDER"] = provider

    results: list[dict] = []
    runs: list[dict] = []  # per-truck workflow logs
    for plate, plate_cases in by_truck.items():
        truck_id = resolve_truck_id(plate)
        if truck_id is None:
            for c in plate_cases:
                results.append({**c, "actual_compliant": None, "error": f"truck '{plate}' not in DB"})
            continue
        state = run_match_workflow(truck_id, use_mock_llm=use_mock)
        if state.get("error"):
            for c in plate_cases:
                results.append({**c, "actual_compliant": None, "error": state["error"]})
            continue
        verdict_by_load: dict[int, dict] = {v["load_id"]: v for v in state.get("compliance_results", [])}
        runs.append({
            "plate": plate,
            "truck_id": truck_id,
            "analyst_log": state.get("analyst_log", {}),
            "decision_load": state.get("decision", {}).get("chosen_load_id"),
        })
        for c in plate_cases:
            v = verdict_by_load.get(c["load_id"])
            if v is None:
                results.append({**c, "actual_compliant": None, "error": "load_id not in available_loads"})
            else:
                results.append({
                    **c,
                    "actual_compliant": bool(v["is_compliant"]),
                    "actual_blockers": v["blockers"],
                    "actual_cited_rule_ids": v.get("cited_rule_ids", []),
                    "sanity_overrides": v.get("sanity_overrides", []),
                })

    # Confusion matrix
    cm = Counter()
    blocker_misses: list[dict] = []
    for r in results:
        if r.get("actual_compliant") is None:
            cm["error"] += 1
            continue
        exp = r["expected_compliant"]
        act = r["actual_compliant"]
        if exp and act: cm["true_compliant"] += 1
        elif (not exp) and (not act): cm["true_blocked"] += 1
        elif exp and (not act): cm["false_blocked"] += 1
        elif (not exp) and act: cm["false_compliant"] += 1
        # Check expected_blocker substring among cited rule ids
        if not exp and r.get("expected_blocker"):
            cited_str = " ".join(r.get("actual_cited_rule_ids", []))
            if r["expected_blocker"] not in cited_str:
                blocker_misses.append(r)

    total = sum(cm.values()) - cm["error"]
    correct = cm["true_compliant"] + cm["true_blocked"]
    accuracy = correct / total if total else 0.0
    sanity_corrected = sum(1 for r in results if r.get("sanity_overrides"))

    summary = {
        "provider": provider,
        "total_cases": len(results),
        "evaluated": total,
        "errors": cm["error"],
        "correct": correct,
        "accuracy": accuracy,
        "confusion": dict(cm),
        "blocker_id_mismatches": len(blocker_misses),
        "sanity_corrected_count": sanity_corrected,
        "runs": runs,
        "mismatches": [
            {k: r.get(k) for k in (
                "truck_plate", "load_id", "expected_compliant", "actual_compliant",
                "expected_blocker", "actual_blockers", "rationale", "sanity_overrides",
            )}
            for r in results if r.get("actual_compliant") is not None
            and r["expected_compliant"] != r["actual_compliant"]
        ],
    }

    if json_only:
        return summary

    print()
    print(f"== Eval: provider={provider} ==")
    print(f"Total cases:     {summary['total_cases']}")
    print(f"Evaluated:       {summary['evaluated']}  (errors: {summary['errors']})")
    print(f"Correct:         {summary['correct']}")
    print(f"Accuracy:        {accuracy:.1%}")
    print(f"Sanity corrected: {sanity_corrected} verdicts (LLM disagreed with hard rules)")
    print()
    print("Confusion matrix:")
    print(f"  true_compliant  : {cm['true_compliant']:4d}    (expected ✓, actual ✓)")
    print(f"  true_blocked    : {cm['true_blocked']:4d}    (expected ✗, actual ✗)")
    print(f"  false_compliant : {cm['false_compliant']:4d}    (expected ✗, actual ✓ — should be blocked but passes)")
    print(f"  false_blocked   : {cm['false_blocked']:4d}    (expected ✓, actual ✗ — should pass but blocked)")
    print(f"  errors          : {cm['error']:4d}")
    print()
    if summary["mismatches"]:
        print(f"Mismatches ({len(summary['mismatches'])}):")
        for m in summary["mismatches"][:10]:
            sgn = "✓→✗" if m["expected_compliant"] else "✗→✓"
            blk = (m.get("actual_blockers") or [""])[0][:80]
            print(f"  {sgn}  {m['truck_plate']:12s} L{m['load_id']:2d}  expected={m['expected_compliant']!s:5s} got={m['actual_compliant']!s:5s}  {blk}")
            if m.get("rationale"):
                print(f"        rationale: {m['rationale'][:100]}")
    if blocker_misses:
        print()
        print(f"Blocker-id mismatches ({len(blocker_misses)}): blocked correctly but cited wrong rule")
        for m in blocker_misses[:5]:
            print(f"  {m['truck_plate']} L{m['load_id']}: expected '{m['expected_blocker']}' substring in {m.get('actual_cited_rule_ids')}")
    print()
    print("Per-truck runs:")
    for r in runs:
        log = r["analyst_log"]
        print(f"  {r['plate']:12s} mode={log.get('mode'):8s} compliant={log.get('compliant_count')}/{log.get('evaluated_loads')} "
              f"llm={log.get('llm_calls', 0)} cached={log.get('cache_hits', 0)} "
              f"sanity_corrected={log.get('sanity_overrides_count', 0)} {log.get('elapsed_ms')}ms")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the Analyst against ground truth.")
    parser.add_argument("--provider", choices=["mock", "gemini", "anthropic", "auto"],
                        default="mock", help="LLM provider for evaluation (default: mock).")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON only (no human-readable table).")
    args = parser.parse_args()
    summary = evaluate(args.provider, json_only=args.json)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

"""Verify the four PR4 experiments still hold under live Gemini.

Runs each experiment twice — once with the deterministic mock evaluator
(default mode used in the thesis writeup) and once with live Gemini Flash
gated by the post-LLM sanity layer — then prints a side-by-side
comparison and a global verdict.

Why this script exists. The route planner consumes only the boolean
`is_compliant` field from the compliance dict; it does not look at LLM
reasoning prose. The sanity layer overrides any LLM disagreement on the
hard rules. So in theory mock and Gemini should produce identical
numerical results. This script is the empirical confirmation.

  python -m scripts.verify_with_gemini                # all 4 experiments
  python -m scripts.verify_with_gemini --json > out.json
  python -m scripts.verify_with_gemini --only A,C     # subset
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts import (  # noqa: E402
    exp_a_margin_lift, exp_b_compliance_value,
    exp_c_broker_lift, exp_d_fleet_scaling,
)


@dataclass
class Metric:
    name: str
    mock: float | int | None
    gemini: float | int | None

    @property
    def diff(self) -> float | None:
        if self.mock is None or self.gemini is None:
            return None
        try:
            return float(self.gemini) - float(self.mock)
        except (TypeError, ValueError):
            return None

    @property
    def relative_diff_pct(self) -> float | None:
        if self.mock is None or self.gemini is None:
            return None
        try:
            mock_f = float(self.mock)
            gemini_f = float(self.gemini)
        except (TypeError, ValueError):
            return None
        if mock_f == 0:
            return 0.0 if gemini_f == 0 else float("inf")
        return (gemini_f - mock_f) / abs(mock_f) * 100

    @property
    def status(self) -> str:
        if self.mock is None and self.gemini is None:
            return "—"
        if self.mock is None or self.gemini is None:
            return "✗"   # one side missing
        rel = self.relative_diff_pct
        if rel is None:
            # Non-numeric values: compare as strings/equality.
            return "✅" if self.mock == self.gemini else "✗"
        if rel == 0.0:
            return "✅"
        if abs(rel) < 1.0:
            return "⚠ <1%"
        if abs(rel) < 5.0:
            return "⚠ <5%"
        return "✗ >5%"


def extract_metrics_a(result: dict) -> list[Metric]:
    """Pull the headline numbers from Experiment A."""
    d = result["delta"]
    return [
        Metric("baseline margin €", d["margin_baseline_eur"], None),
        Metric("treatment margin €", d["margin_treatment_eur"], None),
        Metric("margin lift €", d["margin_lift_eur"], None),
        Metric("baseline deadhead %", d["deadhead_baseline_pct"], None),
        Metric("treatment deadhead %", d["deadhead_treatment_pct"], None),
        Metric("treatment utilisation %", d["utilisation_treatment_pct"], None),
        Metric("treatment empty km", d["empty_km_treatment"], None),
        Metric("chains in treatment", d["chains_in_treatment"], None),
    ]


def extract_metrics_b(result: dict) -> list[Metric]:
    b, t = result["baseline"], result["treatment"]
    return [
        Metric("baseline gross margin €", b["gross_margin_eur"], None),
        Metric("baseline violation count", b["violation_count"], None),
        Metric("baseline fine exposure €", b["total_fine_exposure_eur"], None),
        Metric("baseline NET margin €", b["net_margin_after_fines_eur"], None),
        Metric("treatment gross margin €", t["gross_margin_eur"], None),
        Metric("treatment violation count", t["violation_count"], None),
    ]


def extract_metrics_c(result: dict) -> list[Metric]:
    d = result["delta"]
    return [
        Metric("customer-only margin €", d["margin_baseline_eur"], None),
        Metric("treatment margin €", d["margin_treatment_eur"], None),
        Metric("margin lift €", d["margin_lift_eur"], None),
        Metric("treatment deadhead %", d["deadhead_treatment_pct"], None),
        Metric("treatment utilisation %", d["utilisation_treatment_pct"], None),
        Metric("chains in treatment", d["chains_treatment"], None),
        Metric("chains with broker leg", d["chains_with_broker_load"], None),
        Metric("customer served (treatment)", d["customer_served_treatment"], None),
        Metric("broker served (treatment)", d["broker_served_treatment"], None),
    ]


def extract_metrics_d(result: dict) -> list[Metric]:
    out = []
    for p in result["points"]:
        n = p["fleet_size"]
        out.append(Metric(f"N={n}: total margin €", p["total_margin_eur"], None))
        out.append(Metric(f"N={n}: deadhead %", p["deadhead_pct"], None))
        out.append(Metric(f"N={n}: chains", p["chain_trips_count"], None))
    return out


EXPERIMENTS: dict[str, dict] = {
    "A": {
        "title": "Margin + utilisation lift",
        "run": exp_a_margin_lift.run,
        "extract": extract_metrics_a,
    },
    "B": {
        "title": "Compliance violation avoidance",
        "run": exp_b_compliance_value.run,
        "extract": extract_metrics_b,
    },
    "C": {
        "title": "Customer + broker freight lift",
        "run": exp_c_broker_lift.run,
        "extract": extract_metrics_c,
    },
    "D": {
        "title": "Fleet-size scaling",
        "run": exp_d_fleet_scaling.run,
        "extract": extract_metrics_d,
    },
}


def verify_one(exp_id: str) -> tuple[list[Metric], dict]:
    """Run one experiment under both modes; return (metrics, raw_runs)."""
    spec = EXPERIMENTS[exp_id]
    print(f"  ▶ {exp_id}: running mock-LLM…", file=sys.stderr)
    mock_result = spec["run"](use_mock_llm=True)
    print(f"  ▶ {exp_id}: running live Gemini…", file=sys.stderr)
    gemini_result = spec["run"](use_mock_llm=False)

    mock_metrics = spec["extract"](mock_result)
    gemini_metrics = spec["extract"](gemini_result)

    # Stitch both sides into Metric objects keyed by name.
    by_name = {m.name: Metric(m.name, m.mock, None) for m in mock_metrics}
    for m in gemini_metrics:
        if m.name in by_name:
            by_name[m.name] = Metric(m.name, by_name[m.name].mock, m.mock)
        else:
            by_name[m.name] = Metric(m.name, None, m.mock)
    metrics = list(by_name.values())
    return metrics, {"mock": mock_result, "gemini": gemini_result}


def _print_table(exp_id: str, title: str, metrics: list[Metric]) -> None:
    print()
    print("=" * 90)
    print(f"  Experiment {exp_id} — {title}")
    print("=" * 90)
    print(f"  {'metric':35s}  {'mock':>12s}  {'gemini':>12s}  {'Δ':>12s}  status")
    print(f"  {'-'*35}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*8}")
    for m in metrics:
        mock_s = f"{m.mock:>12}" if m.mock is not None else "         —  "
        gemini_s = f"{m.gemini:>12}" if m.gemini is not None else "         —  "
        diff = m.diff
        diff_s = f"{diff:>+12.2f}" if isinstance(diff, float) else "        —   "
        print(f"  {m.name:35s}  {mock_s}  {gemini_s}  {diff_s}  {m.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="A,B,C,D",
                        help="Comma-separated experiment IDs to verify (default: all).")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Emit machine-readable JSON to stdout.")
    parser.add_argument("--out", default=str(BACKEND_DIR / "docs" / "verify_with_gemini.json"),
                        help="Write the JSON bundle here as well.")
    args = parser.parse_args()

    chosen = [x.strip().upper() for x in args.only.split(",") if x.strip()]
    bad = [x for x in chosen if x not in EXPERIMENTS]
    if bad:
        parser.error(f"unknown experiment IDs: {bad}")

    overall: dict[str, dict] = {}
    total_metrics = 0
    matched = 0
    drifts = []

    for exp_id in chosen:
        metrics, raw = verify_one(exp_id)
        overall[exp_id] = {
            "title": EXPERIMENTS[exp_id]["title"],
            "metrics": [
                {"name": m.name, "mock": m.mock, "gemini": m.gemini,
                 "diff": m.diff, "rel_diff_pct": m.relative_diff_pct,
                 "status": m.status}
                for m in metrics
            ],
        }
        if not args.as_json:
            _print_table(exp_id, EXPERIMENTS[exp_id]["title"], metrics)
        for m in metrics:
            total_metrics += 1
            if m.status.startswith("✅"):
                matched += 1
            elif m.status.startswith("✗"):
                drifts.append((exp_id, m))

    summary = {
        "total_metrics": total_metrics,
        "matched_exactly": matched,
        "match_rate_pct": round(matched / total_metrics * 100, 1) if total_metrics else 0.0,
        "drifts": [
            {"experiment": e, "metric": m.name, "mock": m.mock, "gemini": m.gemini}
            for e, m in drifts
        ],
        "verdict": "TRUTHFUL" if not drifts else "DIVERGED",
    }
    overall["__summary__"] = summary

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(overall, indent=2, default=str))
    print(f"\n[verify] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)

    if not args.as_json:
        print()
        print("=" * 90)
        print(f"  GLOBAL — {summary['matched_exactly']}/{summary['total_metrics']} "
              f"metrics matched ({summary['match_rate_pct']}%) — verdict: {summary['verdict']}")
        if drifts:
            print(f"  Drifts:")
            for e, m in drifts:
                print(f"    Exp {e}: {m.name}  mock={m.mock}  gemini={m.gemini}")
        print("=" * 90)
    else:
        print(json.dumps(overall, indent=2, default=str))

    sys.exit(0 if not drifts else 1)


if __name__ == "__main__":
    main()

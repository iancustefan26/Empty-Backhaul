"""R3 — Fleet growth story: when to add vans, when to open a second depot?

Hypothesis.
    Single-depot growth shows clear diminishing returns: adding the
    10th van to a Cluj fleet earns less than the 5th. At equal total
    fleet size (14 vans), splitting 7 + 7 across Cluj + Bucureşti
    serves more loads AND earns more total margin than 14 vans all in
    Cluj — geographic coverage beats density past the saturation point.

Why this experiment matters.
    A small carrier owner asks "should I grow my Cluj fleet from 7 to
    14 vans, or open a second 7-van location in Bucureşti?". R3 answers
    with concrete daily-margin numbers for a hand-picked growth path.
    (R4 then formalises this with a 32-cell parameter sweep.)

Method.
    Run the planner for each of 7 hand-picked configurations:

      Single Cluj: 3, 7, 14, 25 vans
      Dual depots: Cluj + Bucureşti (7+7 = 14)
      Triple depots: Cluj + Bucureşti + Timişoara (7+7+7 = 21)
                     Cluj + Bucureşti + Constanţa (7+7+7 = 21)

    Record headline metrics per config and compare against the
    7-van Cluj baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.fleet_workflow import analyst_fleet  # noqa: E402
from app.agents.route_planner import plan_fleet_routes  # noqa: E402
from app.services import load_123cargo as l123c  # noqa: E402
from scripts._123cargo_common import (  # noqa: E402
    assert_invariants, build_homogeneous_fleet, provenance_block, write_json,
)


CONFIGS = [
    {"label": "single-cluj-3",       "n_vans": 3,  "depots": ["Cluj-Napoca"]},
    {"label": "single-cluj-7",       "n_vans": 7,  "depots": ["Cluj-Napoca"]},
    {"label": "single-cluj-14",      "n_vans": 14, "depots": ["Cluj-Napoca"]},
    {"label": "single-cluj-25",      "n_vans": 25, "depots": ["Cluj-Napoca"]},
    {"label": "dual-cluj-buc-14",    "n_vans": 14, "depots": ["Cluj-Napoca", "Bucuresti"]},
    {"label": "triple-cbt-21",       "n_vans": 21, "depots": ["Cluj-Napoca", "Bucuresti", "Timisoara"]},
    {"label": "triple-cbc-21",       "n_vans": 21, "depots": ["Cluj-Napoca", "Bucuresti", "Constanta"]},
]
BASELINE = "single-cluj-7"


def _summary(plan: dict | None, n_vans: int) -> dict:
    if plan is None:
        return {"total_margin_eur": 0.0, "vans_dispatched": 0,
                "loads_served": 0, "deadhead_pct": 0.0,
                "fleet_utilization_pct": 0.0, "chains_formed": 0,
                "singles_formed": 0, "margin_per_van": 0.0}
    dispatched = len(plan["plans"]) - plan["idle_count"]
    return {
        "total_margin_eur":      round(plan["total_fleet_margin_eur"], 2),
        "vans_dispatched":       dispatched,
        "loads_served":          sum(len(p["load_ids"]) for p in plan["plans"]),
        "deadhead_pct":          round(plan["deadhead_ratio"] * 100, 2),
        "fleet_utilization_pct": plan["fleet_utilization_pct"],
        "chains_formed":         plan["chain_trips_count"],
        "singles_formed":        plan["single_trips_count"],
        "margin_per_van":        round(plan["total_fleet_margin_eur"] / n_vans, 2),
    }


def run() -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    dataset_meta = l123c.load_dataset()
    loads = l123c.all_snapshots()

    per_config = []
    baseline_margin = None
    for cfg in CONFIGS:
        vans = build_homogeneous_fleet(
            n_vans=cfg["n_vans"], depot_cities=cfg["depots"],
        )
        compliance, _ = analyst_fleet(vans, loads, use_mock_llm=True)
        cell_t0 = time.perf_counter()
        opt = plan_fleet_routes(vans, loads, compliance, top_k=1, enable_chains=True)
        cell_ms = int((time.perf_counter() - cell_t0) * 1000)
        plan = opt["alternatives"][0] if opt["alternatives"] else None
        s = _summary(plan, cfg["n_vans"])
        s.update({
            "label":           cfg["label"],
            "n_vans":          cfg["n_vans"],
            "n_depots":        len(cfg["depots"]),
            "depots":          cfg["depots"],
            "solver_status":   opt["optimiser_status"],
            "solve_ms":        cell_ms,
        })
        if cfg["label"] == BASELINE:
            baseline_margin = s["total_margin_eur"]
        per_config.append(s)
        print(f"[r3] {cfg['label']:<22}  margin €{s['total_margin_eur']:>5.0f}  "
              f"dispatched {s['vans_dispatched']:>2}/{cfg['n_vans']:<2}  "
              f"deadhead {s['deadhead_pct']:.1f}%", file=sys.stderr)

    # Marginal lift over baseline + per-van trend
    for s in per_config:
        s["margin_lift_vs_baseline_eur"] = round(
            s["total_margin_eur"] - (baseline_margin or 0), 2,
        )

    # Diminishing-returns "knee": for the single-depot Cluj curve, find
    # the smallest size where adding the next van earns < €100/day
    single_cluj_curve = sorted(
        (s for s in per_config if s["label"].startswith("single-cluj")),
        key=lambda x: x["n_vans"],
    )
    knee = None
    for i in range(1, len(single_cluj_curve)):
        delta_van = single_cluj_curve[i]["n_vans"] - single_cluj_curve[i-1]["n_vans"]
        delta_margin = (single_cluj_curve[i]["total_margin_eur"]
                        - single_cluj_curve[i-1]["total_margin_eur"])
        per_van_added = delta_margin / max(1, delta_van)
        if per_van_added < 100:
            knee = {
                "from_size":   single_cluj_curve[i-1]["n_vans"],
                "to_size":     single_cluj_curve[i]["n_vans"],
                "per_van_eur": round(per_van_added, 2),
            }
            break

    # Single-vs-multi at equal total fleet (14 vans)
    single14 = next((s for s in per_config if s["label"] == "single-cluj-14"), None)
    dual14 = next((s for s in per_config if s["label"] == "dual-cluj-buc-14"), None)
    multi_vs_single_14 = None
    if single14 and dual14:
        multi_vs_single_14 = {
            "single_margin":      single14["total_margin_eur"],
            "dual_margin":        dual14["total_margin_eur"],
            "margin_lift_eur":    round(dual14["total_margin_eur"] - single14["total_margin_eur"], 2),
            "margin_lift_pct":    round(
                (dual14["total_margin_eur"] - single14["total_margin_eur"])
                / single14["total_margin_eur"] * 100, 2,
            ) if single14["total_margin_eur"] > 0 else None,
            "loads_served_delta": dual14["loads_served"] - single14["loads_served"],
        }

    elapsed = time.perf_counter() - t0
    result = {
        "experiment_id": "R3",
        "title": "Fleet growth: single-depot scaling vs multi-depot expansion",
        "hypothesis": (
            "Single-depot growth diminishes; equal-fleet multi-depot configs "
            "earn more margin AND serve more loads than single-depot at the "
            "same total fleet size."
        ),
        "inputs": {
            "configurations":     [c["label"] for c in CONFIGS],
            "n_loads":            len(loads),
            "baseline_config":    BASELINE,
            "dataset_scraped_at": dataset_meta.get("scraped_at_utc"),
        },
        "results": {
            "per_config":          per_config,
            "diminishing_returns_knee_single_cluj": knee,
            "multi_vs_single_at_fleet_14":         multi_vs_single_14,
        },
        "details": {
            "wall_time_seconds":   round(elapsed, 2),
        },
        "provenance": provenance_block(dataset_meta=dataset_meta),
    }

    _assert(result)
    return result


def _assert(result: dict) -> None:
    rows = result["results"]["per_config"]
    by_label = {r["label"]: r for r in rows}

    # Monotonicity: single-Cluj 25 ≥ single-Cluj 3 (more vans → ≥ margin)
    s3 = by_label.get("single-cluj-3")
    s25 = by_label.get("single-cluj-25")
    mono_ok = (s3 is None or s25 is None
               or s25["total_margin_eur"] >= s3["total_margin_eur"] - 1e-6)

    # Geographic-coverage check: dual-14 should serve ≥ single-14 loads
    s14 = by_label.get("single-cluj-14")
    d14 = by_label.get("dual-cluj-buc-14")
    cov_ok = (s14 is None or d14 is None
              or d14["loads_served"] >= s14["loads_served"])

    # Every config gets a valid solver status
    status_ok = all(
        r["solver_status"] in ("OPTIMAL", "FEASIBLE", "ALL_IDLE") for r in rows
    )

    checks = [
        (mono_ok,
         "single-Cluj 25 ≥ single-Cluj 3 on total margin (monotonicity)",
         "Adding vans must not decrease margin; check CP-SAT objective "
         "in app/agents/fleet_strategist.py"),
        (cov_ok,
         "dual-depot 14 ≥ single-depot 14 on loads_served "
         "(geographic coverage wins past saturation)",
         "If single-depot serves more, the dual-depot van placement is "
         "wrong; check build_homogeneous_fleet round-robin in "
         "scripts/_123cargo_common.py"),
        (status_ok,
         "every configuration returns a valid solver status",
         "Inspect plan_fleet_routes for constraint feasibility regressions"),
    ]
    assert_invariants(checks)


def _print_human(r: dict) -> None:
    print()
    print("=" * 90)
    print(f"  R3 — Fleet scaling on {r['inputs']['n_loads']} real Frigo loads")
    print("=" * 90)
    print()
    print(f"  {'config':<22}  {'vans':>5}  {'depots':>7}  {'margin €':>10}  "
          f"{'€/van':>7}  {'loads':>6}  {'deadh%':>7}")
    print("  " + "-" * 74)
    for c in r["results"]["per_config"]:
        print(f"  {c['label']:<22}  {c['n_vans']:>5}  {c['n_depots']:>7}  "
              f"{c['total_margin_eur']:>10.0f}  {c['margin_per_van']:>7.0f}  "
              f"{c['loads_served']:>6}  {c['deadhead_pct']:>7.1f}")
    print()
    knee = r["results"]["diminishing_returns_knee_single_cluj"]
    if knee:
        print(f"  Diminishing returns knee (single-Cluj curve): "
              f"adding van #{knee['from_size']+1}-{knee['to_size']} "
              f"earns €{knee['per_van_eur']:.0f}/van (below €100/van threshold)")
    else:
        print(f"  No diminishing-returns knee detected in single-Cluj curve "
              f"(every added van earns ≥ €100/day on this dataset)")
    msd = r["results"]["multi_vs_single_at_fleet_14"]
    if msd:
        print(f"  At fleet=14: dual (Cluj+Bucureşti) earns €{msd['dual_margin']:.0f} "
              f"vs single Cluj €{msd['single_margin']:.0f} — "
              f"{msd['margin_lift_pct']:+.1f}% lift, "
              f"{msd['loads_served_delta']:+d} more loads served")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()
    result = run()
    out = write_json("exp_r3", result)
    print(f"[r3] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

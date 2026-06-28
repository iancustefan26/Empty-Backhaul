"""R2 — Depot location sensitivity: where to base the 7-van fleet?

Hypothesis.
    The same 7-van fleet earns dramatically different daily margin
    depending on the depot city, because the real Frigo market is
    Bucureşti-centric (22/89 loads originate in Bucureşti, only 3 in
    Cluj). At least one alternative depot earns ≥ 2× the Cluj baseline,
    and the best vs worst depot differ by at least 50 %.

Why this experiment matters.
    A practitioner deciding "should I open my reefer business in
    Cluj or move to Bucureşti?" needs concrete daily-margin numbers
    for each candidate depot, on the real freight market.

Method.
    For each of 5 depot cities (Cluj-Napoca, Bucureşti, Timişoara,
    Iaşi, Constanţa), rebuild the same 7-van fleet starting at that
    city and run the planner on the 89 real Frigo loads.
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

# Hardcoded 5-candidate set spanning Romania geography.
# (R4 uses data-driven priority instead; R2 deliberately tests the
# practitioner's mental shortlist regardless of dataset density.)
CANDIDATE_DEPOTS = [
    "Cluj-Napoca",   # central-west
    "Bucuresti",     # capital
    "Timisoara",     # west
    "Iasi",          # north-east (deliberately far from main corridors)
    "Constanta",     # south-east port
]
N_VANS = 7


def _summary(plan: dict | None, n_vans: int) -> dict:
    if plan is None:
        return {"total_margin_eur": 0, "vans_dispatched": 0,
                "loads_served": 0, "chains_formed": 0,
                "deadhead_pct": 0.0, "fleet_utilization_pct": 0.0,
                "total_km": 0, "avg_drive_hours_per_van": 0.0}
    dispatched = len(plan["plans"]) - plan["idle_count"]
    loads_served = sum(len(p["load_ids"]) for p in plan["plans"])
    drive_hours = [p["drive_hours"] for p in plan["plans"] if p["kind"] != "IDLE"]
    return {
        "total_margin_eur":         round(plan["total_fleet_margin_eur"], 2),
        "vans_dispatched":          dispatched,
        "loads_served":             loads_served,
        "chains_formed":            plan["chain_trips_count"],
        "singles_formed":           plan["single_trips_count"],
        "deadhead_pct":             round(plan["deadhead_ratio"] * 100, 2),
        "fleet_utilization_pct":    plan["fleet_utilization_pct"],
        "total_km":                 plan["total_km"],
        "avg_drive_hours_per_van":  round(sum(drive_hours) / len(drive_hours), 2)
                                     if drive_hours else 0.0,
    }


def _top3_routes(plan: dict | None, loads_by_id: dict) -> list[dict]:
    if plan is None:
        return []
    plans = [p for p in plan["plans"] if p["kind"] != "IDLE"]
    plans.sort(key=lambda p: -p["margin_eur"])
    out = []
    for vp in plans[:3]:
        cities = [vp["legs"][0]["from_city"]] + [l["to_city"] for l in vp["legs"]]
        uniq = [cities[0]]
        for c in cities[1:]:
            if c != uniq[-1]:
                uniq.append(c)
        ids = [loads_by_id[lid].get("_origin_123cargo_id", "?")
               for lid in vp["load_ids"] if lid in loads_by_id]
        out.append({
            "van_plate":     vp["van_plate"],
            "route":         " → ".join(uniq),
            "margin_eur":    round(vp["margin_eur"], 2),
            "123cargo_ids":  ids,
        })
    return out


def run() -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    dataset_meta = l123c.load_dataset()
    loads = l123c.all_snapshots()
    loads_by_id = {l["id"]: l for l in loads}

    per_depot = []
    for depot in CANDIDATE_DEPOTS:
        vans = build_homogeneous_fleet(n_vans=N_VANS, depot_cities=[depot])
        compliance, _ = analyst_fleet(vans, loads, use_mock_llm=True)
        opt = plan_fleet_routes(vans, loads, compliance, top_k=1, enable_chains=True)
        plan = opt["alternatives"][0] if opt["alternatives"] else None
        s = _summary(plan, N_VANS)
        s["depot"] = depot
        s["solver_status"] = opt["optimiser_status"]
        s["top_3_routes"] = _top3_routes(plan, loads_by_id)
        per_depot.append(s)
        print(f"[r2] {depot:<12}  margin €{s['total_margin_eur']:>5.0f}  "
              f"dispatched {s['vans_dispatched']}/{N_VANS}  "
              f"loads {s['loads_served']}  "
              f"deadhead {s['deadhead_pct']:.1f}%", file=sys.stderr)

    # Aggregate winners by metric
    def _best_by(metric: str, lower_is_better: bool = False):
        candidates = [d for d in per_depot if d["vans_dispatched"] > 0]
        if not candidates:
            return None
        return min(candidates, key=lambda d: d[metric]) if lower_is_better \
            else max(candidates, key=lambda d: d[metric])

    winners = {
        "by_margin":     (_best_by("total_margin_eur") or {}).get("depot"),
        "by_loads_served": (_best_by("loads_served") or {}).get("depot"),
        "by_utilization": (_best_by("fleet_utilization_pct") or {}).get("depot"),
        "by_low_deadhead": (_best_by("deadhead_pct", lower_is_better=True) or {}).get("depot"),
    }

    margins = [d["total_margin_eur"] for d in per_depot if d["vans_dispatched"] > 0]
    best_vs_worst_ratio = max(margins) / min(margins) if margins and min(margins) > 0 else None

    elapsed = time.perf_counter() - t0
    result = {
        "experiment_id": "R2",
        "title": "Depot location sensitivity — where to base the 7-van fleet?",
        "hypothesis": (
            "Real freight market is Bucureşti-centric (22/89 loads vs 3/89 "
            "in Cluj); at least one alternative depot earns ≥ 2× Cluj, and "
            "best-vs-worst depots differ by ≥ 50 %."
        ),
        "inputs": {
            "n_vans":            N_VANS,
            "candidate_depots":  CANDIDATE_DEPOTS,
            "n_loads":           len(loads),
            "dataset_scraped_at": dataset_meta.get("scraped_at_utc"),
        },
        "results": {
            "per_depot":          per_depot,
            "winners":            winners,
            "best_vs_worst_ratio": (round(best_vs_worst_ratio, 2)
                                    if best_vs_worst_ratio is not None else None),
        },
        "details": {
            "wall_time_seconds":  round(elapsed, 2),
        },
        "provenance": provenance_block(dataset_meta=dataset_meta),
    }

    _assert(result)
    return result


def _assert(result: dict) -> None:
    rows = result["results"]["per_depot"]
    dispatchers = [r for r in rows if r["vans_dispatched"] > 0]

    checks = [
        (all(r["solver_status"] in ("OPTIMAL", "FEASIBLE", "ALL_IDLE")
             for r in rows),
         "every depot run must return a valid solver status",
         "Check plan_fleet_routes in app/agents/route_planner.py for "
         "constraint feasibility regressions"),
        (len(dispatchers) >= 3,
         f"at least 3 of {len(CANDIDATE_DEPOTS)} depots must dispatch ≥ 1 van",
         "If <3 depots succeed, the dataset is too narrow for the candidate "
         "set — consider broadening CANDIDATE_DEPOTS"),
        (len(set(r["total_margin_eur"] for r in dispatchers)) > 1,
         "max_margin_depot ≠ min_margin_depot (else depot location is "
         "irrelevant, which would be implausible for this geography)",
         "Inspect the per-depot margins; if identical, the planner is "
         "ignoring the van's starting position"),
    ]
    assert_invariants(checks)


def _print_human(r: dict) -> None:
    print()
    print("=" * 80)
    print(f"  R2 — Depot location sensitivity ({r['inputs']['n_vans']} vans, "
          f"{r['inputs']['n_loads']} real Frigo loads)")
    print("=" * 80)
    print()
    print(f"  {'depot':<14}  {'margin €':>10}  {'vans':>5}  {'loads':>5}  "
          f"{'deadhead %':>10}  {'avg h':>6}")
    print("  " + "-" * 60)
    for d in r["results"]["per_depot"]:
        print(f"  {d['depot']:<14}  {d['total_margin_eur']:>10.0f}  "
              f"{d['vans_dispatched']:>5}  {d['loads_served']:>5}  "
              f"{d['deadhead_pct']:>10.1f}  {d['avg_drive_hours_per_van']:>6.1f}")
    print()
    w = r["results"]["winners"]
    print("  Winners by metric:")
    print(f"    Highest margin:        {w['by_margin']}")
    print(f"    Most loads served:     {w['by_loads_served']}")
    print(f"    Best utilization:      {w['by_utilization']}")
    print(f"    Lowest deadhead:       {w['by_low_deadhead']}")
    if r["results"]["best_vs_worst_ratio"] is not None:
        print(f"  Best vs worst margin ratio: {r['results']['best_vs_worst_ratio']:.2f}×")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()
    result = run()
    out = write_json("exp_r2", result)
    print(f"[r2] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

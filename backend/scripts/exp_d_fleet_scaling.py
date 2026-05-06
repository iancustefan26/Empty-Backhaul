"""Experiment D — Fleet-size scaling.

Hypothesis. *As fleet size grows, the optimiser exploits more matching
combinations: per-van profitability rises and deadhead falls because more
vans means more chances to find a perfect-fit chain. Diminishing returns
once the fleet exceeds the load supply.*

Method. For N ∈ {3, 5, 7, 10} (the company's actual fleet caps at 10),
keep the same 35-load pool and the same compliance gate, but cap the van
count via the existing `fleet_size` parameter. Subsampling is
deterministic (Sentry returns vans in id order, take the first N).

Metrics tracked per N:
  - total_fleet_margin_eur  (revenue scales linearly? sub- or super-?)
  - margin_per_van_eur      (the network-effect signal)
  - deadhead_ratio
  - customer_loads_served / available
  - chain_trips_count
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.fleet_workflow import analyst_fleet, sentry_fleet  # noqa: E402
from app.agents.route_planner import plan_fleet_routes  # noqa: E402
from scripts._exp_common import BACKEND_DIR, write_json  # noqa: E402

FLEET_SIZES = [3, 5, 7, 10]


def run_one(n: int) -> dict:
    sentry = sentry_fleet(include_broker=True, fleet_size=n)
    if "error" in sentry:
        sys.exit(f"Sentry error at N={n}: {sentry['error']}")
    vans = sentry["fleet"]
    loads = sentry["available_loads"]
    compliance, _ = analyst_fleet(vans, loads, use_mock_llm=True)
    result = plan_fleet_routes(vans, loads, compliance, top_k=1)
    plan = result["alternatives"][0]
    return {
        "fleet_size": len(vans),
        "load_pool_size": len(loads),
        "total_margin_eur": plan["total_fleet_margin_eur"],
        "margin_per_van_eur": round(
            plan["total_fleet_margin_eur"] / len(vans), 2
        ) if vans else 0.0,
        "deadhead_ratio": plan["deadhead_ratio"],
        "deadhead_pct": round(plan["deadhead_ratio"] * 100, 2),
        "fleet_utilization_pct": plan["fleet_utilization_pct"],
        "single_trips_count": plan["single_trips_count"],
        "chain_trips_count": plan["chain_trips_count"],
        "idle_count": plan["idle_count"],
        "customer_loads_served": plan["customer_loads_served"],
        "customer_loads_available": plan["customer_loads_available"],
        "broker_loads_served": plan["broker_loads_served"],
        "candidate_singles": result["candidate_singles"],
        "candidate_chains": result["candidate_chains"],
        "elapsed_ms": result["elapsed_ms"],
    }


def run() -> dict:
    points = [run_one(n) for n in FLEET_SIZES]
    return {
        "experiment": "D — Fleet-size scaling",
        "sweep": FLEET_SIZES,
        "points": points,
    }


def _print_human(result: dict) -> None:
    print()
    print("=" * 100)
    print("  Experiment D — Fleet-size scaling")
    print("=" * 100)
    print(f"  {'N':>3s}  {'margin €':>10s}  {'€/van':>8s}  {'deadhead %':>11s}  "
          f"{'util %':>7s}  {'chains':>7s}  {'cust SLA':>10s}  {'wall ms':>7s}")
    print(f"  {'-'*3}  {'-'*10}  {'-'*8}  {'-'*11}  {'-'*7}  {'-'*7}  {'-'*10}  {'-'*7}")
    for p in result["points"]:
        print(f"  {p['fleet_size']:>3d}  €{p['total_margin_eur']:>9.2f}  "
              f"€{p['margin_per_van_eur']:>7.2f}  {p['deadhead_pct']:>10.2f}%  "
              f"{p['fleet_utilization_pct']:>6.1f}%  {p['chain_trips_count']:>7d}  "
              f"{p['customer_loads_served']}/{p['customer_loads_available']:<4d}      {p['elapsed_ms']:>7d}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()

    result = run()
    out = write_json("exp_d", result)
    print(f"[exp_d] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

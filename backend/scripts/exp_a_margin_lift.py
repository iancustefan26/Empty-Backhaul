"""Experiment A — Fleet margin + utilisation lift via coordinated planning.

Hypothesis. *Compared to a naive nearest-pickup dispatcher running
independent round trips per van, our depot-model route planner with
multi-leg chains delivers a ≥30% net margin lift and a meaningful
utilisation increase, while keeping deadhead in the same range.*

Baseline. Each van independently picks its closest profitable compliant
load, completes the round trip (depot → pickup → delivery → depot), and
returns to depot. No fleet coordination, no chains. Conflicts (two vans
choosing the same load) resolved first-come-first-served by van id. This
is the typical Romanian SMB dispatcher behaviour: one driver, one phone
call.

Treatment. Our route planner with chains enabled.

Both variants share the same compliant load pool — the comparison
isolates the *coordinated planning + chains* contribution.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.route_planner import (  # noqa: E402
    DayPlan, FleetPlanStats, _idle_plan, _single_plan, plan_fleet_routes,
)
from app.agents.state import LoadSnapshot, TruckSnapshot  # noqa: E402
from scripts._exp_common import EXP_DIR, hydrate, write_json  # noqa: E402


def naive_dispatch(
    vans: list[TruckSnapshot],
    loads: list[LoadSnapshot],
    compliance: dict,
) -> FleetPlanStats:
    """Per-van greedy nearest-pickup; no chains, no coordination."""
    available_load_ids: set[int] = {l["id"] for l in loads}
    customer_load_ids = {l["id"] for l in loads if l.get("source") == "customer"}
    broker_load_ids = {l["id"] for l in loads if l.get("source") == "broker"}

    chosen_plans: list[DayPlan] = []
    for v in sorted(vans, key=lambda x: x["id"]):
        candidates = []
        for l in loads:
            if l["id"] not in available_load_ids:
                continue
            verdict = compliance.get((v["id"], l["id"]))
            if verdict is None or not verdict["is_compliant"]:
                continue
            plan = _single_plan(v, l)
            if plan is None:
                continue
            candidates.append(plan)
        if not candidates:
            chosen_plans.append(_idle_plan(v))
            continue
        # Naive: nearest pickup wins (smallest leg-1 empty km), tie-break by margin
        candidates.sort(key=lambda p: (p["legs"][0]["km"], -p["margin_eur"]))
        chosen = candidates[0]
        chosen_plans.append(chosen)
        available_load_ids.discard(chosen["load_ids"][0])

    total_loaded = sum(p["loaded_km"] for p in chosen_plans)
    total_empty = sum(p["empty_km"] for p in chosen_plans)
    total_km = total_loaded + total_empty
    served = {lid for p in chosen_plans for lid in p["load_ids"]}
    served_customer = len(served & customer_load_ids)
    served_broker = len(served & broker_load_ids)
    idle = sum(1 for p in chosen_plans if p["kind"] == "IDLE")
    utilisation = (len(chosen_plans) - idle) / len(vans) * 100 if vans else 0.0

    return FleetPlanStats(
        rank=1, objective_value_cents=int(round(sum(p["margin_eur"] for p in chosen_plans) * 100)),
        total_fleet_margin_eur=round(sum(p["margin_eur"] for p in chosen_plans), 2),
        total_loaded_km=round(total_loaded, 1),
        total_empty_km=round(total_empty, 1),
        total_km=round(total_km, 1),
        deadhead_ratio=round(total_empty / total_km, 4) if total_km else 0.0,
        fleet_utilization_pct=round(utilisation, 1),
        single_trips_count=sum(1 for p in chosen_plans if p["kind"] == "SINGLE"),
        chain_trips_count=0,    # naive never chains
        idle_count=idle,
        customer_loads_served=served_customer,
        customer_loads_available=len(customer_load_ids),
        broker_loads_served=served_broker,
        broker_loads_available=len(broker_load_ids),
        unserved_customer_load_ids=sorted(customer_load_ids - served),
        plans=chosen_plans,
    )


def run(*, use_mock_llm: bool = True) -> dict:
    ctx = hydrate(include_broker=True, use_mock_llm=use_mock_llm)
    vans, loads, compliance = ctx["vans"], ctx["loads"], ctx["compliance"]

    baseline = naive_dispatch(vans, loads, compliance)
    treatment_result = plan_fleet_routes(vans, loads, compliance, top_k=1)
    if not treatment_result["alternatives"]:
        sys.exit("Route planner returned no plan; check seed.")
    treatment = treatment_result["alternatives"][0]

    delta = {
        "margin_baseline_eur": baseline["total_fleet_margin_eur"],
        "margin_treatment_eur": treatment["total_fleet_margin_eur"],
        "margin_lift_eur": round(
            treatment["total_fleet_margin_eur"] - baseline["total_fleet_margin_eur"], 2
        ),
        "margin_lift_pct": (
            round(
                (treatment["total_fleet_margin_eur"] - baseline["total_fleet_margin_eur"])
                / baseline["total_fleet_margin_eur"] * 100, 1
            )
            if baseline["total_fleet_margin_eur"] else None
        ),
        "utilisation_baseline_pct": baseline["fleet_utilization_pct"],
        "utilisation_treatment_pct": treatment["fleet_utilization_pct"],
        "utilisation_lift_pp": round(
            treatment["fleet_utilization_pct"] - baseline["fleet_utilization_pct"], 1
        ),
        "deadhead_baseline_pct": round(baseline["deadhead_ratio"] * 100, 2),
        "deadhead_treatment_pct": round(treatment["deadhead_ratio"] * 100, 2),
        "deadhead_delta_pp": round(
            (treatment["deadhead_ratio"] - baseline["deadhead_ratio"]) * 100, 2
        ),
        "empty_km_baseline": baseline["total_empty_km"],
        "empty_km_treatment": treatment["total_empty_km"],
        "empty_km_delta": round(treatment["total_empty_km"] - baseline["total_empty_km"], 1),
        "loaded_km_baseline": baseline["total_loaded_km"],
        "loaded_km_treatment": treatment["total_loaded_km"],
        "chains_in_treatment": treatment["chain_trips_count"],
    }
    return {
        "experiment": "A — Margin + utilisation lift",
        "fleet_size": len(vans),
        "load_pool_size": len(loads),
        "depot": vans[0]["current_city"] if vans else None,
        "compliance_compliant_pairs": ctx["analyst_log"]["compliant_pairs"],
        "baseline": baseline,
        "treatment": treatment,
        "delta": delta,
    }


def _print_human(result: dict) -> None:
    d = result["delta"]
    print()
    print("=" * 80)
    print(f"  Experiment A — Margin + utilisation lift  "
          f"(fleet={result['fleet_size']}, loads={result['load_pool_size']}, depot={result['depot']})")
    print("=" * 80)
    print(f"  Net margin €    baseline {d['margin_baseline_eur']:8.2f}  →  treatment {d['margin_treatment_eur']:8.2f}  "
          f"(+€{d['margin_lift_eur']}, +{d['margin_lift_pct']}%)")
    print(f"  Utilisation %   baseline {d['utilisation_baseline_pct']:5.1f}%   →  treatment {d['utilisation_treatment_pct']:5.1f}%   "
          f"(+{d['utilisation_lift_pp']} pp)")
    print(f"  Deadhead %      baseline {d['deadhead_baseline_pct']:5.2f}%   →  treatment {d['deadhead_treatment_pct']:5.2f}%   "
          f"({d['deadhead_delta_pp']:+.2f} pp)")
    print(f"  Empty km        baseline {d['empty_km_baseline']:8.1f}  →  treatment {d['empty_km_treatment']:8.1f}  "
          f"({d['empty_km_delta']:+.1f} km)")
    print(f"  Chains used     baseline 0 (none possible)  →  treatment {d['chains_in_treatment']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for the per-pair Analyst (default: mock).")
    args = parser.parse_args()

    result = run(use_mock_llm=not args.gemini)
    out = write_json("exp_a", result)
    print(f"[exp_a] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

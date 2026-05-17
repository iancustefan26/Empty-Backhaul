"""Experiment C — Customer + broker freight lift (THE HEADLINE STORY).

Hypothesis. *Adding spot-market broker freight to the load pool gives the
optimiser the backhaul opportunities it needs to chain trips, dramatically
lifting net margin and slashing deadhead km. This is exactly the
'find-backhaul-freight-so-you-don't-drive-empty' value proposition.*

Baseline. `include_broker = False` — the planner only sees direct customer
loads. Vans with no profitable customer round trip stay idle.

Treatment. `include_broker = True` — full pool of customer + broker
freight. Chains can mix sources (a customer load out + a broker backhaul
home).

Both use the same compliance + planning stack. The only delta is the
broker pool.
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


def run_one(include_broker: bool, *, use_mock_llm: bool = True) -> dict:
    sentry = sentry_fleet(include_broker=include_broker, fleet_size=15)
    if "error" in sentry:
        sys.exit(f"Sentry error: {sentry['error']}")
    vans = sentry["fleet"]
    loads = sentry["available_loads"]
    compliance, alog = analyst_fleet(vans, loads, use_mock_llm=use_mock_llm)
    result = plan_fleet_routes(vans, loads, compliance, top_k=1)
    plan = result["alternatives"][0]
    return {
        "include_broker": include_broker,
        "load_pool_size": len(loads),
        "plan": plan,
    }


def run(*, use_mock_llm: bool = True) -> dict:
    baseline = run_one(include_broker=False, use_mock_llm=use_mock_llm)
    treatment = run_one(include_broker=True, use_mock_llm=use_mock_llm)

    bp = baseline["plan"]
    tp = treatment["plan"]

    chains_using_broker = sum(
        1 for p in tp["plans"]
        if p["kind"] == "CHAIN"
        and any(
            sum(1 for leg in p["legs"]
                if leg.get("load_id") is not None
                and leg["load_id"] in {l_id for l_id in p["load_ids"]})
            for _ in [None]
        )
    )
    # Better metric: chains with at least one broker load
    # We need to look up loads to know source. Re-fetch from treatment context.
    sentry = sentry_fleet(include_broker=True, fleet_size=15)
    by_load_source = {l["id"]: l.get("source") for l in sentry["available_loads"]}
    chains_with_broker = 0
    for p in tp["plans"]:
        if p["kind"] != "CHAIN":
            continue
        sources = {by_load_source.get(lid) for lid in p["load_ids"]}
        if "broker" in sources:
            chains_with_broker += 1

    delta = {
        "load_pool_baseline": baseline["load_pool_size"],
        "load_pool_treatment": treatment["load_pool_size"],
        "broker_loads_added": treatment["load_pool_size"] - baseline["load_pool_size"],
        "margin_baseline_eur": bp["total_fleet_margin_eur"],
        "margin_treatment_eur": tp["total_fleet_margin_eur"],
        "margin_lift_eur": round(
            tp["total_fleet_margin_eur"] - bp["total_fleet_margin_eur"], 2
        ),
        "margin_lift_pct": (
            round(
                (tp["total_fleet_margin_eur"] - bp["total_fleet_margin_eur"])
                / bp["total_fleet_margin_eur"] * 100, 1
            )
            if bp["total_fleet_margin_eur"] else None
        ),
        "deadhead_baseline_pct": round(bp["deadhead_ratio"] * 100, 2),
        "deadhead_treatment_pct": round(tp["deadhead_ratio"] * 100, 2),
        "deadhead_reduction_pp": round(
            (bp["deadhead_ratio"] - tp["deadhead_ratio"]) * 100, 2
        ),
        "empty_km_baseline": bp["total_empty_km"],
        "empty_km_treatment": tp["total_empty_km"],
        "empty_km_saved": round(bp["total_empty_km"] - tp["total_empty_km"], 1),
        "utilisation_baseline_pct": bp["fleet_utilization_pct"],
        "utilisation_treatment_pct": tp["fleet_utilization_pct"],
        "utilisation_lift_pp": round(
            tp["fleet_utilization_pct"] - bp["fleet_utilization_pct"], 1
        ),
        "chains_baseline": bp["chain_trips_count"],
        "chains_treatment": tp["chain_trips_count"],
        "chains_with_broker_load": chains_with_broker,
        "customer_served_baseline": bp["customer_loads_served"],
        "customer_served_treatment": tp["customer_loads_served"],
        "broker_served_treatment": tp["broker_loads_served"],
    }
    return {
        "experiment": "C — Customer + broker freight lift",
        "baseline": baseline,
        "treatment": treatment,
        "delta": delta,
    }


def _print_human(result: dict) -> None:
    d = result["delta"]
    print()
    print("=" * 80)
    print("  Experiment C — Customer + broker freight lift")
    print("=" * 80)
    print(f"  Load pool      baseline {d['load_pool_baseline']} (customer-only)  →  treatment {d['load_pool_treatment']} (customer + {d['broker_loads_added']} broker)")
    print(f"  Margin €       baseline {d['margin_baseline_eur']:8.2f}  →  treatment {d['margin_treatment_eur']:8.2f}  (+€{d['margin_lift_eur']}, +{d['margin_lift_pct']}%)")
    print(f"  Deadhead %     baseline {d['deadhead_baseline_pct']:5.2f}%   →  treatment {d['deadhead_treatment_pct']:5.2f}%   (-{d['deadhead_reduction_pp']} pp)")
    print(f"  Empty km       baseline {d['empty_km_baseline']:8.1f}  →  treatment {d['empty_km_treatment']:8.1f}  ({d['empty_km_saved']:+.1f} km saved)")
    print(f"  Utilisation %  baseline {d['utilisation_baseline_pct']:5.1f}%   →  treatment {d['utilisation_treatment_pct']:5.1f}%   (+{d['utilisation_lift_pp']} pp)")
    print(f"  Chains used    baseline {d['chains_baseline']}  →  treatment {d['chains_treatment']}   (of which {d['chains_with_broker_load']} include a broker load)")
    print(f"  Customer SLA   baseline {d['customer_served_baseline']} customer loads served  →  treatment {d['customer_served_treatment']}  (broker served: {d['broker_served_treatment']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for the per-pair Analyst (default: mock).")
    args = parser.parse_args()

    result = run(use_mock_llm=not args.gemini)
    out = write_json("exp_c", result)
    print(f"[exp_c] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

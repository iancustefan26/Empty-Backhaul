"""CLI: end-to-end daily route plan for the Cluj-Napoca van depot.

  python -m scripts.run_route_demo                   # 3 alternatives, mock LLM, customer + broker
  python -m scripts.run_route_demo --top-k 1
  python -m scripts.run_route_demo --customer-only
  python -m scripts.run_route_demo --no-chains       # disable multi-leg chaining
  python -m scripts.run_route_demo --gemini          # live Gemini for citations
  python -m scripts.run_route_demo --json            # machine-readable for the experiments
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


def _route_label(plan: dict) -> str:
    """Human-readable route summary, collapsing same-city successive legs."""
    if plan["kind"] == "IDLE":
        return "depot ↩ (idle)"
    cities: list[str] = []
    for leg in plan["legs"]:
        if not cities or cities[-1] != leg["from_city"]:
            cities.append(leg["from_city"])
        cities.append(leg["to_city"])
    # Collapse consecutive duplicates
    collapsed = []
    for c in cities:
        if not collapsed or collapsed[-1] != c:
            collapsed.append(c)
    return " → ".join(collapsed)


def _print_human(sentry_log: dict, analyst_log: dict, result: dict) -> None:
    print()
    print("=" * 100)
    print("  CLUJ REEFER LOGISTICS — Daily route plan")
    print("=" * 100)
    print(f"  fleet={sentry_log['fleet_size']} vans at depot · {sentry_log['available_load_count']} loads "
          f"({sentry_log['customer_loads']} customer, {sentry_log['broker_loads']} broker)")
    print(f"  analyst: {analyst_log['mode']} · pre_blocked {analyst_log['pre_blocked_pairs']}/"
          f"{analyst_log['pair_count']} · compliant {analyst_log['compliant_pairs']} · "
          f"{analyst_log['elapsed_ms']}ms")
    print(f"  optimiser: {result['optimiser_status']} · "
          f"{result['candidate_singles']} singles + {result['candidate_chains']} chains "
          f"considered · {result['elapsed_ms']}ms")

    for plan in result["alternatives"]:
        print()
        print(f"  ---- Plan {plan['rank']}  total_margin=€{plan['total_fleet_margin_eur']:.2f}  "
              f"empty={plan['total_empty_km']:.1f}km loaded={plan['total_loaded_km']:.1f}km  "
              f"deadhead={plan['deadhead_ratio']*100:.1f}%  utilisation={plan['fleet_utilization_pct']:.1f}% "
              f"(singles={plan['single_trips_count']}, chains={plan['chain_trips_count']}, "
              f"idle={plan['idle_count']})  customer={plan['customer_loads_served']}/"
              f"{plan['customer_loads_available']}  broker={plan['broker_loads_served']}/"
              f"{plan['broker_loads_available']} ----")
        print(f"  {'van':12s}  {'kind':6s}  {'loads':14s}  {'margin €':>10s}  {'km':>6s} "
              f"({'empty':>5s})  route")
        print(f"  {'-'*12}  {'-'*6}  {'-'*14}  {'-'*10}  {'-'*6}  {'-'*7}  {'-'*40}")
        for p in plan["plans"]:
            loads_str = "+".join(f"L{lid}" for lid in p["load_ids"]) or "—"
            print(f"  {p['van_plate']:12s}  {p['kind']:6s}  {loads_str:14s}  "
                  f"€{p['margin_eur']:>9.2f}  {p['total_km']:>6.1f} ({p['empty_km']:>5.1f})  "
                  f"{_route_label(p)}")
        if plan["unserved_customer_load_ids"]:
            print(f"    ⚠ SLA risk — unserved customer loads: {plan['unserved_customer_load_ids']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--customer-only", action="store_true",
                        help="Restrict the load pool to source='customer'.")
    parser.add_argument("--no-chains", action="store_true",
                        help="Disable multi-leg chaining; vans do at most one round trip.")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for the per-pair Analyst step.")
    parser.add_argument("--fleet-size", type=int, default=15)
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Emit JSON to stdout for the experiment harness.")
    args = parser.parse_args()

    sentry_out = sentry_fleet(
        include_broker=not args.customer_only, fleet_size=args.fleet_size,
    )
    if "error" in sentry_out:
        sys.exit(f"Sentry error: {sentry_out['error']}")

    vans = sentry_out["fleet"]
    loads = sentry_out["available_loads"]
    compliance, analyst_log = analyst_fleet(
        vans, loads, use_mock_llm=not args.gemini,
    )
    result = plan_fleet_routes(
        vans, loads, compliance, top_k=args.top_k, enable_chains=not args.no_chains,
    )

    if args.as_json:
        print(json.dumps({
            "sentry_log": sentry_out["sentry_log"],
            "analyst_log": analyst_log,
            "optimiser": result,
        }, indent=2, default=str))
    else:
        _print_human(sentry_out["sentry_log"], analyst_log, result)


if __name__ == "__main__":
    main()

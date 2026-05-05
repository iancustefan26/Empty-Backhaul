"""CLI: run the multi-truck fleet match and pretty-print the top-K plans.

  python -m scripts.run_fleet_demo                            # 3 alternatives, mock LLM, customer + broker
  python -m scripts.run_fleet_demo --top-k 1                  # only the best plan
  python -m scripts.run_fleet_demo --customer-only            # ignore broker freight
  python -m scripts.run_fleet_demo --gemini                   # live Gemini for citations + reasoning
  python -m scripts.run_fleet_demo --json                     # machine-readable for the experiments
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.fleet_workflow import run_fleet_match  # noqa: E402


def _print_human(result: dict) -> None:
    if result["error"]:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    sentry = result["sentry_log"]
    analyst = result["analyst_log"]
    opt = result["optimiser"]

    print()
    print("=" * 100)
    print("  AGENTIC COLD BACKHAUL — FLEET MATCH")
    print("=" * 100)
    print(f"  fleet_size={sentry['fleet_size']}  loads={sentry['available_load_count']} "
          f"(customer={sentry['customer_loads']}, broker={sentry['broker_loads']})")
    print(f"  analyst: mode={analyst['mode']}  pre_blocked_pairs={analyst['pre_blocked_pairs']}/{analyst['pair_count']}  "
          f"compliant={analyst['compliant_pairs']}  llm={analyst['llm_calls']} cached={analyst['cache_hits']} "
          f"sanity_corrected={analyst['sanity_corrections']}  {analyst['elapsed_ms']}ms")
    print(f"  optimiser: status={opt['optimiser_status']}  candidate_pairs={opt['candidate_pairs']} "
          f"alternatives={len(opt['alternatives'])}  {opt['elapsed_ms']}ms")

    for plan in opt["alternatives"]:
        print()
        print(f"  ---- Plan {plan['rank']}  total_margin=€{plan['total_margin_eur']:.2f}  "
              f"empty={plan['total_empty_km']:.1f}km  loaded={plan['total_loaded_km']:.1f}km  "
              f"deadhead={plan['deadhead_ratio']*100:.1f}%  utilisation={plan['fleet_utilization_pct']:.1f}%  "
              f"customer={plan['customer_loads_served']}/{plan['customer_loads_available']}  "
              f"broker={plan['broker_loads_served']}/{plan['broker_loads_available']} ----")
        print(f"  {'truck':12s}  {'load':4s}  {'cargo':18s}  {'route':28s}  {'empty':>7s}  {'loaded':>7s}  {'margin':>9s}  source")
        print(f"  {'-'*12}  {'-'*4}  {'-'*18}  {'-'*28}  {'-'*7}  {'-'*7}  {'-'*9}  -------")
        for a in plan["assignments"]:
            if a["load_id"] is None:
                print(f"  {a['truck_plate']:12s}  IDLE  ({a['truck_current_city']})")
            else:
                route = f"{a['load_pickup_city']}->{a['load_delivery_city']}"
                print(f"  {a['truck_plate']:12s}  L{a['load_id']:<3d}  {a['cargo_type']:18s}  "
                      f"{route:28s}  {a['empty_km']:6.1f}  {a['loaded_km']:6.1f}  "
                      f"€{a['margin_eur']:8.2f}  {a['source']}")
        if plan["unserved_customer_load_ids"]:
            print(f"    SLA risk — unserved customer loads: {plan['unserved_customer_load_ids']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=3, help="Number of alternative plans (1-5).")
    parser.add_argument("--customer-only", action="store_true",
                        help="Restrict the load pool to source='customer'.")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for the per-pair Analyst step (cached).")
    parser.add_argument("--fleet-size", type=int, default=15)
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Emit JSON to stdout (for the experiment harness).")
    args = parser.parse_args()

    result = run_fleet_match(
        top_k=args.top_k,
        include_broker=not args.customer_only,
        use_mock_llm=not args.gemini,
        fleet_size=args.fleet_size,
    )

    if args.as_json:
        # Drop the un-serialisable compliance dict (caller can hit the API for that).
        out = {k: v for k, v in result.items() if k != "compliance"}
        print(json.dumps(out, indent=2, default=str))
        return

    _print_human(result)


if __name__ == "__main__":
    main()

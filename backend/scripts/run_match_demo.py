"""CLI: end-to-end agent demo for a single truck.

    python -m scripts.run_match_demo --plate B-202-CBO --mock-llm
    python -m scripts.run_match_demo --truck-id 9
    python -m scripts.run_match_demo --plate B-909-CBO --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402

from app.agents.workflow import run_match_workflow  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402


def _resolve_truck_id(plate: str | None, truck_id: int | None) -> int:
    if truck_id is not None:
        return truck_id
    if plate is None:
        raise SystemExit("Provide --plate or --truck-id")
    if SessionLocal is None:
        raise SystemExit("SUPABASE_DATABASE_URL is not configured")
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT id FROM trucks WHERE plate_number = :p"), {"p": plate}
        ).first()
    if row is None:
        raise SystemExit(f"No truck with plate_number = {plate!r}")
    return int(row.id)


def _print_pretty(state: dict) -> None:
    if state.get("error"):
        print(f"\nERROR: {state['error']}")
        return

    truck = state["truck"]
    print("\n" + "=" * 78)
    print(f"  AGENTIC COLD BACKHAUL — match for {truck['plate_number']}")
    print("=" * 78)

    # Sentry
    log = state["sentry_log"]
    valid_certs = sum(1 for w in truck["wash_certificates"] if w["is_currently_valid"])
    print("\n[1] SENTRY")
    print(f"  Truck   : {truck['plate_number']} ({truck['carrier_name']})")
    print(f"  In      : {truck['current_city']}  ->  home {truck['home_base_city']}")
    print(f"  Capab.  : {truck['temp_capability']}")
    print(f"  Last    : {truck['last_cargo']}   pharma_logger={truck['has_pharma_logger']}   "
          f"hours_left={truck['remaining_driving_hours']}")
    print(f"  Status  : {truck['status']}")
    print(f"  Wash certs on file: {len(truck['wash_certificates'])} "
          f"(currently valid: {valid_certs})")
    print(f"  Available loads to evaluate: {log['available_load_count']}")

    # Analyst
    a = state["analyst_log"]
    print(f"\n[2] ANALYST  ({a['mode']}{', model='+a['model'] if a.get('model') else ''}, "
          f"{a['elapsed_ms']} ms, {a['rag_hits']} rule-hits)")
    print(f"  Compliant: {a['compliant_count']} / {a['evaluated_loads']}")
    print(f"\n  {'#':>3}  {'cargo':<18} {'route':<27} {'verdict':<10}  blocker / reasoning")
    print(f"  {'-'*3}  {'-'*18} {'-'*27} {'-'*10}  {'-'*40}")
    by_id = {l["id"]: l for l in state["available_loads"]}
    for v in state["compliance_results"]:
        load = by_id[v["load_id"]]
        verdict = "OK" if v["is_compliant"] else "REJECT"
        first_msg = (v["blockers"][0] if v["blockers"]
                     else (v["warnings"][0] if v["warnings"] else v["reasoning"][:60]))
        print(f"  {load['id']:>3}  {load['cargo_type']:<18} "
              f"{load['pickup_city']+'->'+load['delivery_city']:<27} "
              f"{verdict:<10}  {first_msg[:60]}")

    # Strategist
    d = state["decision"]
    print(f"\n[3] STRATEGIST  (OR-Tools status={d['optimiser_status']})")
    if d["chosen_load_id"] is None:
        print(f"  -> No assignment.  {d['explanation']}")
    else:
        chosen = d["chosen_load"]
        print(f"  -> CHOSEN: load #{d['chosen_load_id']} {chosen['cargo_type']} "
              f"{chosen['pickup_city']}->{chosen['delivery_city']}")
        print(f"     deadhead = {d['empty_detour_km']} km   loaded = {d['loaded_km']} km   "
              f"price = EUR {chosen['price_eur']}   margin = EUR {d['expected_margin_eur']}")
        print(f"     {d['explanation']}")

    print("\n  Score table (top 5):")
    print(f"  {'#':>3}  {'cargo':<18} {'compliant':<9} {'detour':>7} {'loaded':>7} "
          f"{'price':>8} {'margin':>8}")
    print(f"  {'-'*3}  {'-'*18} {'-'*9} {'-'*7} {'-'*7} {'-'*8} {'-'*8}")
    for row in d["score_table"][:5]:
        print(f"  {row['load_id']:>3}  {row['cargo_type']:<18} "
              f"{('YES' if row['compliant'] else 'no'):<9} "
              f"{row['empty_detour_km']:>7} {row['loaded_km']:>7} "
              f"{row['price_eur']:>8} {row['expected_margin_eur']:>8}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Sentry/Analyst/Strategist pipeline.")
    parser.add_argument("--plate", help="Truck plate number (e.g. B-202-CBO)")
    parser.add_argument("--truck-id", type=int)
    parser.add_argument("--mock-llm", action="store_true",
                        help="Use the deterministic mock Analyst (no Anthropic API call).")
    parser.add_argument("--json", action="store_true",
                        help="Dump the full WorkflowState as JSON instead of pretty-printing.")
    args = parser.parse_args()

    truck_id = _resolve_truck_id(args.plate, args.truck_id)
    state = run_match_workflow(truck_id, use_mock_llm=args.mock_llm)

    if args.json:
        print(json.dumps(state, indent=2, default=str))
    else:
        _print_pretty(state)


if __name__ == "__main__":
    main()

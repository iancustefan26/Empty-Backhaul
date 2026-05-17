"""Experiment T2 — Backhaul chains vs single trips
                  (Strategist contribution, chains on/off).

Hypothesis.
    Enabling 2-leg backhaul chains lifts net €margin by ≥ 35 % at
    fleet_size = 25 with the 75-load broker pool, AND drops the
    deadhead ratio from ~30 % to ≤ 15 %. Chains remain valuable
    (still ≥ 10 % margin lift) when the broker spot market is thin
    (25 loads instead of 75) — a robustness check that chains aren't
    an artefact of having abundant return-leg supply.

Why this experiment isolates the chain value.
    Both arms call exactly the same `plan_fleet_routes()` with
    identical Sentry + Analyst inputs and the same CP-SAT model. The
    only difference is `enable_chains` (True vs False). Whatever
    margin lift / deadhead drop we measure is therefore attributable
    to the chain candidate-generation logic — not to better assignment
    (T1) or better compliance (A1) or a different solver.

Method.
    1. hydrate() once at fleet_size=25 (live Gemini when --gemini,
       mock otherwise).
    2. Headline run: plan_fleet_routes(enable_chains=True) vs
       (enable_chains=False), full 75-load broker pool, fleet=25.
    3. Per-chain breakdown table: for every chain in the chains-on
       plan, record van plate, leg-1 / leg-2 routes, km totals,
       fill_factor (loaded_km / total_km), margin.
    4. Robustness sensitivity matrix at fleet ∈ {10, 15, 25} ×
       broker_density ∈ {25, 50, 75} (9 cells). Each cell reports
       chains_on - chains_off margin delta % and deadhead delta pp.
    5. Customer-SLA impact: chains_on customer_served vs chains_off
       customer_served — chains shouldn't *hurt* customer coverage.

Invariants.
    - chains_formed > 0 in the headline chains-on run (else the seed
      has no chain opportunities → investigate broker pool density).
    - chains_on_margin ≥ chains_off_margin at every cell (CP-SAT with
      chains is a structural superset).
    - chains_on_deadhead_pp ≤ chains_off_deadhead_pp at the headline
      (the whole point of chains).
    - per-chain loaded_km > 0 and fill_factor > 0.5 (a "chain" that's
      mostly empty isn't a chain — sanity-check the chain generator).

Reproduction.
    python -m scripts.exp_t2_chains_value             # mock
    python -m scripts.exp_t2_chains_value --gemini    # live Gemini
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.route_planner import plan_fleet_routes  # noqa: E402
from app.agents.state import LoadSnapshot  # noqa: E402
from scripts._exp_common import (  # noqa: E402
    assert_invariants, cost_meter_summary, hydrate,
    provenance_block, write_v2_json,
)

HEADLINE_FLEET = 25
SENSITIVITY_FLEETS = [10, 15, 25]
SENSITIVITY_BROKER_DENSITIES = [25, 50, 75]


def _subset_loads(loads: list[LoadSnapshot], *, broker_density: int) -> list[LoadSnapshot]:
    """Keep ALL customer loads + the first `broker_density` broker loads
    (ordered by id, which is insertion order in the seed). This keeps
    the customer book intact while thinning the spot market."""
    customers = [l for l in loads if l.get("source") == "customer"]
    brokers = [l for l in loads if l.get("source") == "broker"]
    brokers_kept = sorted(brokers, key=lambda l: l["id"])[:broker_density]
    return customers + brokers_kept


def _run_pair(vans, loads, compliance) -> dict:
    """Return (chains_on, chains_off) FleetPlanStats dicts."""
    on = plan_fleet_routes(vans, loads, compliance, top_k=1, enable_chains=True)
    off = plan_fleet_routes(vans, loads, compliance, top_k=1, enable_chains=False)
    on_stats = on["alternatives"][0] if on["alternatives"] else None
    off_stats = off["alternatives"][0] if off["alternatives"] else None
    return {"on": on_stats, "off": off_stats}


def _summarise_chains(stats: dict) -> list[dict]:
    """Per-chain breakdown table from a FleetPlanStats."""
    chains = []
    for p in stats.get("plans", []):
        if p["kind"] != "CHAIN":
            continue
        cities = [p["legs"][0]["from_city"]] + [l["to_city"] for l in p["legs"]]
        total_km = p["total_km"] or 1e-9
        chains.append({
            "van_plate": p["van_plate"],
            "leg_1": f"{p['legs'][0]['from_city']}→{p['legs'][1]['to_city']}",
            "leg_2": f"{p['legs'][2]['from_city']}→{p['legs'][3]['to_city']}"
                     if len(p["legs"]) >= 4 else "—",
            "cities_visited": " → ".join(cities),
            "total_km": p["total_km"],
            "loaded_km": p["loaded_km"],
            "empty_km": p["empty_km"],
            "fill_factor": round(p["loaded_km"] / total_km, 3),
            "margin_eur": p["margin_eur"],
        })
    return chains


def _delta_pct(on_v: float, off_v: float) -> float | None:
    if off_v == 0:
        return None
    return round((on_v - off_v) / off_v * 100, 1)


def run(*, use_mock_llm: bool = True) -> dict:
    started = datetime.now(timezone.utc)

    ctx = hydrate(include_broker=True, fleet_size=HEADLINE_FLEET, use_mock_llm=use_mock_llm)
    vans, loads, compliance = ctx["vans"], ctx["loads"], ctx["compliance"]

    # ---- Headline pair: fleet=25, broker_density=75 ----
    headline = _run_pair(vans, loads, compliance)
    h_on, h_off = headline["on"], headline["off"]

    headline_summary = {
        "fleet_size": len(vans),
        "broker_density": sum(1 for l in loads if l.get("source") == "broker"),
        "chains_on": {
            "total_margin_eur": h_on["total_fleet_margin_eur"],
            "total_loaded_km": h_on["total_loaded_km"],
            "total_empty_km": h_on["total_empty_km"],
            "total_km": h_on["total_km"],
            "deadhead_pct": round(h_on["deadhead_ratio"] * 100, 2),
            "chains_formed": h_on["chain_trips_count"],
            "singles_formed": h_on["single_trips_count"],
            "idle_count": h_on["idle_count"],
            "customer_served": h_on["customer_loads_served"],
            "customer_available": h_on["customer_loads_available"],
            "broker_served": h_on["broker_loads_served"],
            "broker_available": h_on["broker_loads_available"],
            "fleet_utilization_pct": h_on["fleet_utilization_pct"],
        },
        "chains_off": {
            "total_margin_eur": h_off["total_fleet_margin_eur"],
            "total_loaded_km": h_off["total_loaded_km"],
            "total_empty_km": h_off["total_empty_km"],
            "total_km": h_off["total_km"],
            "deadhead_pct": round(h_off["deadhead_ratio"] * 100, 2),
            "chains_formed": h_off["chain_trips_count"],
            "singles_formed": h_off["single_trips_count"],
            "idle_count": h_off["idle_count"],
            "customer_served": h_off["customer_loads_served"],
            "customer_available": h_off["customer_loads_available"],
            "broker_served": h_off["broker_loads_served"],
            "broker_available": h_off["broker_loads_available"],
            "fleet_utilization_pct": h_off["fleet_utilization_pct"],
        },
        "deltas": {
            "margin_delta_eur": round(h_on["total_fleet_margin_eur"]
                                       - h_off["total_fleet_margin_eur"], 2),
            "margin_delta_pct": _delta_pct(h_on["total_fleet_margin_eur"],
                                           h_off["total_fleet_margin_eur"]),
            "deadhead_delta_pp": round(
                (h_on["deadhead_ratio"] - h_off["deadhead_ratio"]) * 100, 2,
            ),
            "broker_served_delta": h_on["broker_loads_served"] - h_off["broker_loads_served"],
            "customer_served_delta": h_on["customer_loads_served"] - h_off["customer_loads_served"],
            "idle_delta": h_off["idle_count"] - h_on["idle_count"],
        },
    }

    chain_breakdown = _summarise_chains(h_on)

    # ---- Sensitivity matrix (3 × 3) ----
    matrix = []
    for fs in SENSITIVITY_FLEETS:
        for bd in SENSITIVITY_BROKER_DENSITIES:
            sub_vans = sorted(vans, key=lambda v: v["id"])[:fs]
            sub_loads = _subset_loads(loads, broker_density=bd)
            pair = _run_pair(sub_vans, sub_loads, compliance)
            on_s, off_s = pair["on"], pair["off"]
            matrix.append({
                "fleet_size": fs,
                "broker_density": bd,
                "chains_on_margin_eur": on_s["total_fleet_margin_eur"],
                "chains_off_margin_eur": off_s["total_fleet_margin_eur"],
                "margin_delta_pct": _delta_pct(on_s["total_fleet_margin_eur"],
                                                off_s["total_fleet_margin_eur"]),
                "chains_on_deadhead_pct": round(on_s["deadhead_ratio"] * 100, 2),
                "chains_off_deadhead_pct": round(off_s["deadhead_ratio"] * 100, 2),
                "deadhead_delta_pp": round(
                    (on_s["deadhead_ratio"] - off_s["deadhead_ratio"]) * 100, 2,
                ),
                "chains_formed": on_s["chain_trips_count"],
            })

    result = {
        "experiment_id": "T2",
        "experiment": "Strategist — backhaul chains vs single trips",
        "agent": "strategist",
        "hypothesis": (
            "Enabling chains lifts margin ≥ 35 % at fleet=25 and drops "
            "deadhead from ~30 % to ≤ 15 %. Lift remains ≥ 10 % at thin "
            "broker markets (25 loads)."
        ),
        "inputs": {
            "headline_fleet": HEADLINE_FLEET,
            "headline_broker_density": headline_summary["broker_density"],
            "sensitivity_fleets": SENSITIVITY_FLEETS,
            "sensitivity_broker_densities": SENSITIVITY_BROKER_DENSITIES,
            "depot": vans[0]["current_city"] if vans else None,
        },
        "results": {
            "headline": headline_summary,
            "chain_breakdown": chain_breakdown,
            "sensitivity_matrix": matrix,
        },
        "provenance": provenance_block(
            mode="mock" if use_mock_llm else "gemini",
            model=ctx["analyst_log"].get("model"),
        ),
        "cost_meter": cost_meter_summary(since=started),
    }

    _assert_invariants(result)
    return result


def _assert_invariants(result: dict) -> None:
    h = result["results"]["headline"]
    chains = result["results"]["chain_breakdown"]
    matrix = result["results"]["sensitivity_matrix"]

    chains_formed = h["chains_on"]["chains_formed"]
    chains_on_margin = h["chains_on"]["total_margin_eur"]
    chains_off_margin = h["chains_off"]["total_margin_eur"]
    chains_on_deadhead = h["chains_on"]["deadhead_pct"]
    chains_off_deadhead = h["chains_off"]["deadhead_pct"]

    # Matrix-wide structural invariant
    matrix_on_ge_off = all(
        c["chains_on_margin_eur"] + 1e-6 >= c["chains_off_margin_eur"] for c in matrix
    )

    fills_ok = all(c["fill_factor"] > 0.5 and c["loaded_km"] > 0 for c in chains)

    assert_invariants([
        (chains_formed > 0,
         "Headline chains-on run must form at least one chain",
         "Seed has no chain opportunities. Check broker_load_fixtures() in "
         "scripts/seed_data.py — Cluj→X / X→Cluj pairs in the same cargo class."),
        (chains_on_margin + 1e-6 >= chains_off_margin,
         "Headline chains-on margin must be ≥ chains-off margin",
         "plan_fleet_routes(enable_chains=True) is a superset of "
         "(enable_chains=False); investigate route_planner.py:293."),
        (chains_on_deadhead <= chains_off_deadhead + 0.5,
         f"Headline chains-on deadhead ({chains_on_deadhead} %) should be "
         f"≤ chains-off deadhead ({chains_off_deadhead} %)",
         "Chain candidate generator may be packing in empty legs; review "
         "_chain_plan() in app/agents/route_planner.py:212"),
        (matrix_on_ge_off,
         "chains_on_margin ≥ chains_off_margin in every sensitivity cell",
         "Solver inconsistency. Check no-good cuts / objective in "
         "app/agents/route_planner.py::plan_fleet_routes()"),
        (fills_ok,
         "Every chain must have loaded_km > 0 and fill_factor > 0.5",
         "_chain_plan() in app/agents/route_planner.py:212 — chain "
         "definition may be admitting low-fill legs"),
    ])


def _print_human(r: dict) -> None:
    h = r["results"]["headline"]
    d = h["deltas"]
    on, off = h["chains_on"], h["chains_off"]
    print()
    print("=" * 90)
    print(f"  T2 — Backhaul chains vs single trips  (Strategist agent)")
    print("=" * 90)
    print(f"  Fleet {h['fleet_size']}   broker density {h['broker_density']}   "
          f"depot {r['inputs']['depot']}")
    print()
    print(f"  {'metric':>22}  {'chains OFF':>12}  {'chains ON':>12}  {'delta':>12}")
    print("  " + "-" * 66)
    print(f"  {'total margin €':>22}  {off['total_margin_eur']:>12.0f}  "
          f"{on['total_margin_eur']:>12.0f}  "
          f"{d['margin_delta_eur']:>+8.0f} ({d['margin_delta_pct']:+}%)")
    print(f"  {'deadhead %':>22}  {off['deadhead_pct']:>12.2f}  "
          f"{on['deadhead_pct']:>12.2f}  {d['deadhead_delta_pp']:>+11.2f} pp")
    print(f"  {'chains formed':>22}  {off['chains_formed']:>12}  "
          f"{on['chains_formed']:>12}")
    print(f"  {'singles formed':>22}  {off['singles_formed']:>12}  "
          f"{on['singles_formed']:>12}")
    print(f"  {'idle vans':>22}  {off['idle_count']:>12}  {on['idle_count']:>12}")
    print(f"  {'customer served':>22}  "
          f"{off['customer_served']}/{off['customer_available']:<12}  "
          f"{on['customer_served']}/{on['customer_available']:<12}")
    print(f"  {'broker served':>22}  "
          f"{off['broker_served']}/{off['broker_available']:<12}  "
          f"{on['broker_served']}/{on['broker_available']:<12}")
    print()
    print(f"  Chains formed (showing first 5 of {len(r['results']['chain_breakdown'])}):")
    for c in r["results"]["chain_breakdown"][:5]:
        print(f"    {c['van_plate']:14}  {c['cities_visited']:34}  "
              f"{c['total_km']:>5.0f} km  fill {c['fill_factor']:.2f}  "
              f"€{c['margin_eur']:>6.0f}")
    print()
    print(f"  Sensitivity matrix (margin delta %  /  deadhead delta pp):")
    print(f"                broker=25     broker=50     broker=75")
    for fs in SENSITIVITY_FLEETS:
        line = f"    fleet={fs:>2}     "
        for bd in SENSITIVITY_BROKER_DENSITIES:
            cell = next((c for c in r["results"]["sensitivity_matrix"]
                         if c["fleet_size"] == fs and c["broker_density"] == bd), None)
            if cell:
                line += f"{cell['margin_delta_pct']:+5.0f}% / {cell['deadhead_delta_pp']:+5.1f}   "
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for Analyst verdicts (default: mock).")
    args = parser.parse_args()

    result = run(use_mock_llm=not args.gemini)
    out = write_v2_json("exp_t2", result)
    print(f"[exp_t2] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

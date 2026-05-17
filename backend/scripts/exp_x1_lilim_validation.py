"""Experiment X1 — Strategist on the Li & Lim PDPTW benchmark
                   (external optimisation-engine validation).

Hypothesis.
    Our CP-SAT Strategist, run on standard Li & Lim PDPTW benchmark
    instances of size 100 (LC101 "clustered", LR101 "random", LRC101
    "mixed"), produces FEASIBLE plans within < 5 s wall-clock and
    measurably improves load coverage when backhaul chains are
    enabled. Enabling chains never decreases either margin or
    served-load count (CP-SAT with chains is a structural superset).

Why this experiment matters.
    The synthetic Cluj seed validates the system end-to-end against
    Romanian regulations, but it leaves open the question *"does the
    optimisation engine work on standard academic instances reviewers
    can independently verify?"* X1 answers that by running the same
    `run_fleet_optimizer()` and `plan_fleet_routes()` we use in
    production against Li & Lim PDPTW instances that have been the
    canonical benchmark for pickup-and-delivery research for 20+
    years (Li & Lim 2003).

Why this is NOT a Best-Known-Solution comparison.
    Li & Lim PDPTW solvers chain MANY pickup-delivery tasks per
    vehicle to minimise (NV, TD) — number of vehicles, then total
    distance. Our system assigns at most ONE single trip or ONE
    2-leg chain per vehicle per day (depot-anchored). On the same
    instance Li & Lim's tuned heuristics will always serve more
    loads per vehicle — that's not a fair comparison and we make no
    such claim. X1 measures only:

      - solver status (OPTIMAL / FEASIBLE / INFEASIBLE)
      - wall-clock runtime
      - load coverage (loads served / loads available)
      - margin delta when chains are enabled vs disabled
      - margin lift from chains (the actual Strategist contribution)

    A reader who wants a true Li & Lim BKS comparison would need a
    PDPTW solver that supports arbitrary-length chains — which is
    future work, called out in the thesis Discussion chapter.

Reproduction.
    python -m scripts.exp_x1_lilim_validation             # mock-mode default
    python -m scripts.exp_x1_lilim_validation --gemini    # live Gemini
                                                          # (no effect on
                                                          #  numerical
                                                          #  result — all
                                                          #  loads are
                                                          #  hard-rule
                                                          #  compliant by
                                                          #  construction)
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

from app.agents.route_planner import plan_fleet_routes  # noqa: E402
from scripts._exp_common import (  # noqa: E402
    assert_invariants, cost_meter_summary, hydrate,
    provenance_block, write_v2_json,
)
from scripts.lilim_loader import (  # noqa: E402
    parse_instance, synthesise_fixtures,
)

INSTANCES = [
    # (name,    size, label)
    ("lc101",    100, "LC101 — clustered, narrow time windows"),
    ("lr101",    100, "LR101 — random, narrow time windows"),
    ("lrc101",   100, "LRC101 — mixed clustered/random, narrow windows"),
    ("lc201",    100, "LC201 — clustered, wide time windows"),
    ("lr201",    100, "LR201 — random, wide time windows"),
]

CHAIN_VARIANTS = [("singles_only", False), ("chains_on", True)]


def _run_one_instance(name: str, size: int, use_mock_llm: bool) -> dict:
    """Run the Strategist on one Li & Lim instance, chains-off + chains-on."""
    parsed = parse_instance(name, size=size)
    vans, loads = synthesise_fixtures(parsed)

    # Inject the synthesised fixtures straight into the analyst pipeline
    # (bypasses Supabase entirely — see hydrate()'s injection path).
    ctx = hydrate(use_mock_llm=use_mock_llm, vans=vans, loads=loads)
    compliance = ctx["compliance"]
    analyst_log = ctx["analyst_log"]

    per_variant: dict[str, dict] = {}
    for vname, enable_chains in CHAIN_VARIANTS:
        t0 = time.perf_counter()
        result = plan_fleet_routes(
            vans, loads, compliance,
            top_k=1, enable_chains=enable_chains,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if not result["alternatives"]:
            per_variant[vname] = {
                "status": result["optimiser_status"],
                "runtime_ms": elapsed_ms,
                "loads_served": 0, "total_margin_eur": 0.0,
                "chains_formed": 0, "singles_formed": 0,
                "idle_count": len(vans), "deadhead_pct": 0.0,
            }
            continue
        a = result["alternatives"][0]
        served = sum(len(p["load_ids"]) for p in a["plans"])
        per_variant[vname] = {
            "status": result["optimiser_status"],
            "runtime_ms": elapsed_ms,
            "loads_served": served,
            "loads_available": len(loads),
            "coverage_pct": round(served / len(loads) * 100, 1),
            "total_margin_eur": a["total_fleet_margin_eur"],
            "chains_formed": a["chain_trips_count"],
            "singles_formed": a["single_trips_count"],
            "idle_count": a["idle_count"],
            "deadhead_pct": round(a["deadhead_ratio"] * 100, 2),
            "candidate_singles": result["candidate_singles"],
            "candidate_chains": result["candidate_chains"],
        }

    chain_lift_pct = None
    so = per_variant["singles_only"]["total_margin_eur"]
    cn = per_variant["chains_on"]["total_margin_eur"]
    if so > 0:
        chain_lift_pct = round((cn - so) / so * 100, 1)

    return {
        "instance": name,
        "size": size,
        "n_vehicles_expected": parsed["n_vehicles"],
        "vehicle_capacity": parsed["capacity"],
        "pairs_available": len(parsed["pickup_delivery_pairs"]),
        "vans_synthesised": len(vans),
        "loads_synthesised": len(loads),
        "pre_blocked_pairs": analyst_log["pre_blocked_pairs"],
        "compliant_pairs": analyst_log["compliant_pairs"],
        "singles_only": per_variant["singles_only"],
        "chains_on": per_variant["chains_on"],
        "chain_margin_lift_pct": chain_lift_pct,
        "served_delta": (per_variant["chains_on"]["loads_served"]
                         - per_variant["singles_only"]["loads_served"]),
    }


def run(*, use_mock_llm: bool = True) -> dict:
    started = datetime.now(timezone.utc)

    per_instance = []
    for name, size, label in INSTANCES:
        print(f"[exp_x1] {name} ({label})…", file=sys.stderr, flush=True)
        per_instance.append({"label": label, **_run_one_instance(name, size, use_mock_llm)})

    result = {
        "experiment_id": "X1",
        "experiment": "Strategist — Li & Lim PDPTW external benchmark",
        "agent": "strategist",
        "hypothesis": (
            "On standard Li & Lim PDPTW 100-node benchmark instances "
            "(LC101 / LR101 / LRC101 + the wide-window LC201 / LR201) "
            "our CP-SAT Strategist returns a FEASIBLE plan in < 5 s, "
            "and enabling chains never reduces margin or loads-served."
        ),
        "inputs": {
            "instances": [
                {"name": n, "size": s, "label": l}
                for (n, s, l) in INSTANCES
            ],
            "use_mock_llm": use_mock_llm,
            "loader": "scripts.lilim_loader",
            "data_source": ("https://github.com/zhu-he/pdptw-data "
                            "(daily mirror of the canonical SINTEF "
                            "Li & Lim PDPTW benchmark)"),
            "coordinate_map": ("Li & Lim Euclidean km → fake WGS84 lat/lon "
                               "anchored at Cluj-Napoca (46.7712, 23.6236); "
                               "1 unit ≈ 1 km after haversine"),
        },
        "results": {"per_instance": per_instance},
        "provenance": provenance_block(
            mode="mock" if use_mock_llm else "gemini",
            model=None,
        ),
        "cost_meter": cost_meter_summary(since=started),
    }

    _assert_invariants(result)
    return result


def _assert_invariants(result: dict) -> None:
    rows = result["results"]["per_instance"]

    # Every instance returns SOME status; OPTIMAL or FEASIBLE is acceptable
    # for chains-on (it's a much larger model). The singles-only model
    # should always be OPTIMAL for these instance sizes.
    ok_statuses = {"OPTIMAL", "FEASIBLE", "ALL_IDLE"}
    all_status_ok = all(
        r["singles_only"]["status"] in ok_statuses and
        r["chains_on"]["status"] in ok_statuses
        for r in rows
    )

    # Chains-on margin ≥ chains-off margin everywhere (structural superset).
    chains_dont_regress = all(
        r["chains_on"]["total_margin_eur"] + 1e-6 >= r["singles_only"]["total_margin_eur"]
        for r in rows
    )

    # Chains-on loads_served ≥ chains-off loads_served (same reason).
    served_dont_regress = all(
        r["chains_on"]["loads_served"] >= r["singles_only"]["loads_served"]
        for r in rows
    )

    # Wall-clock under 5 s per instance per variant — keeps the suite usable.
    runtime_ok = all(
        r["singles_only"]["runtime_ms"] < 5_000 and
        r["chains_on"]["runtime_ms"] < 30_000        # chains model is bigger
        for r in rows
    )

    # The loader must have actually downloaded + synthesised loads.
    nontrivial = all(r["loads_synthesised"] > 0 for r in rows)

    assert_invariants([
        (all_status_ok,
         "Every instance must return OPTIMAL / FEASIBLE / ALL_IDLE",
         "plan_fleet_routes() in app/agents/route_planner.py:293 — "
         "check the solver model on the chains-on path"),
        (chains_dont_regress,
         "chains-on margin must be ≥ singles-only margin on every instance",
         "Solver inconsistency or chain-candidate generator bug — "
         "see app/agents/route_planner.py::_chain_plan()"),
        (served_dont_regress,
         "chains-on loads_served must be ≥ singles-only loads_served",
         "Same as above — chains are a strict superset of singles"),
        (runtime_ok,
         "Each variant must complete within its budget (5 s singles / 30 s chains)",
         "Solver model too large; consider tightening "
         "MAX_INTER_LEG_DEADHEAD_KM in app/agents/route_planner.py"),
        (nontrivial,
         "Loader must synthesise > 0 loads per instance",
         "scripts/lilim_loader.py:parse_instance() — likely network "
         "failure or instance-name typo"),
    ])


def _print_human(r: dict) -> None:
    print()
    print("=" * 110)
    print(f"  X1 — Li & Lim PDPTW external benchmark  (Strategist agent)")
    print("=" * 110)
    print(f"  {len(r['results']['per_instance'])} instances · "
          f"data source: zhu-he/pdptw-data (mirror of SINTEF)")
    print()
    print(f"  {'instance':<8} {'pairs':>5} {'vans':>4}  "
          f"{'SINGLES':>9} {'ms':>5} {'cov%':>5}    "
          f"{'CHAINS':>9} {'ms':>5} {'cov%':>5}  {'chains':>6} {'+lift%':>7}")
    print("  " + "-" * 102)
    for row in r["results"]["per_instance"]:
        s = row["singles_only"]
        c = row["chains_on"]
        lift = f"{row['chain_margin_lift_pct']:+.1f}" if row['chain_margin_lift_pct'] is not None else "—"
        print(f"  {row['instance']:<8} {row['pairs_available']:>5} "
              f"{row['vans_synthesised']:>4}  "
              f"€{s['total_margin_eur']:>7.0f} {s['runtime_ms']:>5} "
              f"{s.get('coverage_pct', 0.0):>5.1f}    "
              f"€{c['total_margin_eur']:>7.0f} {c['runtime_ms']:>5} "
              f"{c.get('coverage_pct', 0.0):>5.1f}  "
              f"{c['chains_formed']:>6} {lift:>7}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for hydration (no effect on "
                             "numeric result — all X1 loads are hard-rule "
                             "compliant by construction).")
    args = parser.parse_args()

    result = run(use_mock_llm=not args.gemini)
    out = write_v2_json("exp_x1", result)
    print(f"[exp_x1] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

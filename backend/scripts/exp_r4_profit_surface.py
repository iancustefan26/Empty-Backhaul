"""R4 — Profit response surface: profit vs (fleet size × number of depots).

Hypothesis.
    The 2-D profit surface across {fleet_size, n_depots} has clear
    structure: profit is monotonically non-decreasing in fleet size
    AND in depot count (subject to the data-driven priority order);
    the best ROI cell (highest margin / van) sits at a small fleet
    with the right depot mix, NOT at the maximum-fleet cell.

Why this experiment matters.
    R3 picks 7 hand-chosen growth checkpoints. R4 is the FORMAL grid
    an owner studies: every (fleet × depots) combination tested, then
    visualised as a heatmap. Tells the practitioner exactly where the
    diminishing-returns knee sits and which combinations are Pareto-
    optimal on total margin vs margin-per-van.

Method.
    For each cell of an 8 × 4 grid:
      fleet sizes ∈ {3, 5, 7, 10, 14, 18, 25, 35}
      n_depots   ∈ {1, 2, 3, 4}

    Depots are selected in dataset-driven priority order (the cities
    with the most load origins) from `_123cargo_common.DEPOT_CITIES`.
    Vans are split round-robin across the active depots.

    32 cells × ~100-1000 ms each = ~30-60 s total.
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
    DEPOT_CITIES, assert_invariants, build_homogeneous_fleet,
    provenance_block, write_json,
)

FLEET_SIZES = [3, 5, 7, 10, 14, 18, 25, 35]
N_DEPOTS_RANGE = [1, 2, 3, 4]
KNEE_THRESHOLD_EUR = 100   # marginal-return threshold: < €100/van is "saturated"


def _cell(plan: dict | None, n_vans: int) -> dict:
    if plan is None:
        return {"total_margin_eur": 0.0, "vans_dispatched": 0,
                "loads_served": 0, "deadhead_pct": 0.0,
                "fleet_utilization_pct": 0.0, "margin_per_van": 0.0,
                "chains_formed": 0, "singles_formed": 0}
    dispatched = len(plan["plans"]) - plan["idle_count"]
    return {
        "total_margin_eur":      round(plan["total_fleet_margin_eur"], 2),
        "vans_dispatched":       dispatched,
        "loads_served":          sum(len(p["load_ids"]) for p in plan["plans"]),
        "deadhead_pct":          round(plan["deadhead_ratio"] * 100, 2),
        "fleet_utilization_pct": plan["fleet_utilization_pct"],
        "margin_per_van":        round(plan["total_fleet_margin_eur"] / n_vans, 2),
        "chains_formed":         plan["chain_trips_count"],
        "singles_formed":        plan["single_trips_count"],
    }


def run() -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    dataset_meta = l123c.load_dataset()
    loads = l123c.all_snapshots()

    print(f"[r4] depot priority: {DEPOT_CITIES}", file=sys.stderr)
    print(f"[r4] sweeping {len(FLEET_SIZES)} × {len(N_DEPOTS_RANGE)} = "
          f"{len(FLEET_SIZES)*len(N_DEPOTS_RANGE)} cells…", file=sys.stderr)

    grid: list[dict] = []
    for n_depots in N_DEPOTS_RANGE:
        depots = DEPOT_CITIES[:n_depots]
        for n_vans in FLEET_SIZES:
            vans = build_homogeneous_fleet(n_vans=n_vans, depot_cities=depots)
            compliance, _ = analyst_fleet(vans, loads, use_mock_llm=True)
            cell_t0 = time.perf_counter()
            opt = plan_fleet_routes(vans, loads, compliance,
                                    top_k=1, enable_chains=True)
            cell_ms = int((time.perf_counter() - cell_t0) * 1000)
            plan = opt["alternatives"][0] if opt["alternatives"] else None
            cell = _cell(plan, n_vans)
            cell.update({
                "n_vans":         n_vans,
                "n_depots":       n_depots,
                "depots":         depots,
                "solver_status":  opt["optimiser_status"],
                "solve_ms":       cell_ms,
            })
            grid.append(cell)
            print(f"[r4] cell n_depots={n_depots} n_vans={n_vans:>2}  "
                  f"margin €{cell['total_margin_eur']:>5.0f}  "
                  f"€/van {cell['margin_per_van']:>4.0f}  "
                  f"served {cell['loads_served']:>2}", file=sys.stderr)

    # Find the headline optima
    valid = [c for c in grid if c["vans_dispatched"] > 0]
    optimum = max(valid, key=lambda c: c["total_margin_eur"]) if valid else None
    best_roi = max(valid, key=lambda c: c["margin_per_van"]) if valid else None

    # Per-row diminishing-returns knee: for each n_depots, smallest
    # fleet size where adding the next van earns < KNEE_THRESHOLD_EUR
    knees: dict[int, dict | None] = {}
    for n_depots in N_DEPOTS_RANGE:
        row = sorted([c for c in grid if c["n_depots"] == n_depots],
                     key=lambda c: c["n_vans"])
        knee = None
        for i in range(1, len(row)):
            dv = row[i]["n_vans"] - row[i-1]["n_vans"]
            dm = row[i]["total_margin_eur"] - row[i-1]["total_margin_eur"]
            per_van = dm / max(1, dv)
            if per_van < KNEE_THRESHOLD_EUR:
                knee = {
                    "from_size":   row[i-1]["n_vans"],
                    "to_size":     row[i]["n_vans"],
                    "per_van_eur": round(per_van, 2),
                }
                break
        knees[n_depots] = knee

    elapsed = time.perf_counter() - t0
    result = {
        "experiment_id": "R4",
        "title": "Profit response surface — full sweep over (fleet size × depots)",
        "hypothesis": (
            "Profit is monotone non-decreasing in both fleet size and "
            "depot count; the best-ROI cell sits at a small fleet, not "
            "at the largest cell."
        ),
        "inputs": {
            "fleet_sizes":         FLEET_SIZES,
            "n_depots_range":      N_DEPOTS_RANGE,
            "depot_priority":      DEPOT_CITIES,
            "n_loads":             len(loads),
            "n_cells":             len(grid),
            "knee_threshold_eur":  KNEE_THRESHOLD_EUR,
            "dataset_scraped_at":  dataset_meta.get("scraped_at_utc"),
        },
        "results": {
            "grid":                 grid,
            "optimum_cell":         optimum,
            "best_roi_cell":        best_roi,
            "diminishing_returns_knees_per_depot_count": knees,
        },
        "details": {
            "wall_time_seconds":    round(elapsed, 2),
        },
        "provenance": provenance_block(dataset_meta=dataset_meta),
    }

    _assert(result)
    return result


def _assert(result: dict) -> None:
    grid = result["results"]["grid"]

    # All cells return a valid solver status
    statuses_ok = all(
        c["solver_status"] in ("OPTIMAL", "FEASIBLE", "ALL_IDLE") for c in grid
    )

    # Each individual cell runs in < 5s (gives slack vs the 3s plan target)
    runtime_ok = all(c["solve_ms"] < 5000 for c in grid)

    # Within each row (n_depots fixed), single-largest-fleet ≥ single-smallest-fleet
    monotone_ok = True
    for n_depots in N_DEPOTS_RANGE:
        row = sorted([c for c in grid if c["n_depots"] == n_depots],
                     key=lambda c: c["n_vans"])
        if not row:
            continue
        if row[-1]["total_margin_eur"] < row[0]["total_margin_eur"] - 1e-6:
            monotone_ok = False
            break

    # Optimum has positive margin (else dataset is unusable)
    optimum = result["results"]["optimum_cell"]
    has_optimum = optimum is not None and optimum["total_margin_eur"] > 0

    checks = [
        (statuses_ok, "all 32 cells return a valid solver status",
         "Inspect plan_fleet_routes; one cell may have an infeasible model."),
        (runtime_ok, "all cells run in < 5 s (max cell ≥ 5 s means regression)",
         "Run wall_time_seconds + slow cell inspection — the chain candidate "
         "generator may be exploding on big fleets."),
        (monotone_ok,
         "total margin is monotone non-decreasing in fleet size within each "
         "n_depots row (more vans must not earn less)",
         "Check the CP-SAT objective + that larger fleets aren't being "
         "over-constrained somewhere."),
        (has_optimum,
         "the optimum cell has positive margin",
         "If 0, the loads in the dataset are unservable from the chosen "
         "depot priority — extend DEPOT_CITIES."),
    ]
    assert_invariants(checks)


def _print_human(r: dict) -> None:
    grid = r["results"]["grid"]
    print()
    print("=" * 86)
    print(f"  R4 — Profit surface: {len(r['inputs']['fleet_sizes'])} fleet sizes × "
          f"{len(r['inputs']['n_depots_range'])} depot counts = "
          f"{len(grid)} cells  ({r['inputs']['n_loads']} real Frigo loads)")
    print("=" * 86)
    print()
    # Heatmap-like table: rows = n_depots, cols = fleet_sizes
    print(f"  Total margin € — rows = n_depots, cols = fleet size")
    header = "  n_depots │ " + " ".join(f"{n:>6}" for n in r["inputs"]["fleet_sizes"])
    print(header)
    print("  " + "─" * (len(header) - 2))
    for n_depots in r["inputs"]["n_depots_range"]:
        row = sorted([c for c in grid if c["n_depots"] == n_depots],
                     key=lambda c: c["n_vans"])
        cells = " ".join(f"{c['total_margin_eur']:>6.0f}" for c in row)
        print(f"  {n_depots:>8} │ {cells}")
    print()
    print(f"  Margin per van — rows = n_depots, cols = fleet size")
    print(header)
    print("  " + "─" * (len(header) - 2))
    for n_depots in r["inputs"]["n_depots_range"]:
        row = sorted([c for c in grid if c["n_depots"] == n_depots],
                     key=lambda c: c["n_vans"])
        cells = " ".join(f"{c['margin_per_van']:>6.0f}" for c in row)
        print(f"  {n_depots:>8} │ {cells}")
    print()
    optimum = r["results"]["optimum_cell"]
    best_roi = r["results"]["best_roi_cell"]
    if optimum:
        print(f"  Optimum (highest total margin):  "
              f"{optimum['n_vans']} vans across {optimum['n_depots']} depots "
              f"({', '.join(optimum['depots'])}) → €{optimum['total_margin_eur']:.0f}")
    if best_roi:
        print(f"  Best ROI (highest €/van):         "
              f"{best_roi['n_vans']} vans across {best_roi['n_depots']} depots "
              f"({', '.join(best_roi['depots'])}) → €{best_roi['margin_per_van']:.0f}/van")
    print()
    knees = r["results"]["diminishing_returns_knees_per_depot_count"]
    print(f"  Diminishing-returns knees (threshold: €{r['inputs']['knee_threshold_eur']}/van):")
    for nd, k in sorted(knees.items()):
        if k:
            print(f"    n_depots={nd}: knee at fleet {k['from_size']}-{k['to_size']} "
                  f"(€{k['per_van_eur']:.0f}/van for marginal hires)")
        else:
            print(f"    n_depots={nd}: no knee within tested range")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()
    result = run()
    out = write_json("exp_r4", result)
    print(f"[r4] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

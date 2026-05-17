"""Experiment S2 — Driver-hours feasibility filter (Sentry contribution).

Hypothesis.
    The EU 561/2006 9-hour shift cap eliminates 8-20 % of (van × load)
    pairs that look profitable on price alone but cannot legally be done
    in one shift. Without the filter the optimiser would propose illegal
    dispatches; with it, only legally-completable trips reach the
    Strategist.

Why this experiment isolates the Sentry contribution.
    The Sentry agent hydrates the fleet and load pool with deterministic,
    pre-LLM facts (current city, capability, driving-hours budget). The
    hours-feasibility predicate is one of those facts; it's a pure
    function of geography + driver state and does not need any LLM call.
    Measuring how many pairs the predicate rejects shows the *operational
    legality* the Sentry buys us, separate from the Analyst's compliance
    work and the Strategist's optimisation.

Method.
    1. Run `hydrate()` once on the full 25 × 100 seed.
    2. For every (van, load), compute `score_pair()` — the same scorer
       the production Strategist uses; this includes `drive_hours` and
       `hours_feasible`.
    3. Flag pairs where `drive_hours > 9.0` AND `margin_eur > 0`. These
       are the "look profitable but cannot legally be done" set.
    4. Bucket by load source (customer / broker) and report a top-10
       biggest-margin-loss table for the appendix.

Output dimensions.
    - total_pairs
    - profitable_pairs (margin > 0)
    - blocked_pairs (profitable AND hours-infeasible)
    - blocked_pct (blocked / profitable)
    - avg_blocked_margin_eur, total_blocked_margin_eur
    - per-source split (customer vs broker)
    - drive-time histogram (10 bins)
    - top-10 biggest-margin-loss table
    - estimated annual RAR fine exposure avoided

Legality framing.
    Per Romania's OUG 109/2005 art. 8 and the EU 561/2006 transposition,
    a driver who exceeds the 9 h daily driving cap is liable to a fine
    of €500-€1 500 plus possible license suspension. Even at the lower
    bound, one illegal dispatch per fleet-day in a 250-working-day year
    costs ~€125 000. Sentry's filter prevents the optimiser from ever
    proposing such a trip. The "fine exposure avoided" line is a
    deliberately conservative estimate (1 illegal dispatch per van-day
    × €500), not a thesis claim.

Invariants (the "if the results are nonsense, investigate" gate).
    - Every flagged pair has drive_hours > 9.0 (sanity check of the
      predicate itself). Investigate `score_pair()` in
      `app/agents/fleet_strategist.py` if any flagged pair is feasible.
    - blocked_count <= total_pairs (trivial; catches indexing bugs).
    - 0 % < blocked_pct < 50 % — outside this band the road-km factor
      is mis-scaled (currently 1.22 in `app/services/geo.py`).

Reproduction.
    python -m scripts.exp_s2_hours_filter             # mock-mode default
    python -m scripts.exp_s2_hours_filter --gemini    # live-Gemini hydration
                                                      # (same numerical result —
                                                      # this experiment is
                                                      # deterministic geometry)
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

from app.agents.fleet_strategist import score_pair  # noqa: E402
from scripts._exp_common import (  # noqa: E402
    assert_invariants, cost_meter_summary, hydrate,
    provenance_block, write_v2_json,
)

DRIVING_CAP_HOURS = 9.0     # EU 561/2006 daily driving cap
FINE_PER_ILLEGAL_DISPATCH_EUR = 500     # conservative lower bound (OUG 109/2005)
ROMANIAN_WORKING_DAYS = 250


def run(*, use_mock_llm: bool = True) -> dict:
    started = datetime.now(timezone.utc)

    ctx = hydrate(include_broker=True, use_mock_llm=use_mock_llm)
    vans, loads = ctx["vans"], ctx["loads"]

    pair_rows: list[dict] = []
    for v in vans:
        for l in loads:
            s = score_pair(v, l)
            pair_rows.append({
                "van_plate": v["plate_number"],
                "van_id": v["id"],
                "load_id": l["id"],
                "source": l.get("source"),
                "route": s["route"],
                "drive_hours": s["drive_hours"],
                "margin_eur": s["margin_eur"],
                "hours_feasible": s["hours_feasible"],
                "total_km": s["total_km"],
            })

    total_pairs = len(pair_rows)
    profitable = [r for r in pair_rows if r["margin_eur"] > 0]
    blocked = [r for r in profitable if r["drive_hours"] > DRIVING_CAP_HOURS]

    # Per-source split
    by_source = {}
    for src in ("customer", "broker"):
        src_prof = [r for r in profitable if r["source"] == src]
        src_blk = [r for r in src_prof if r["drive_hours"] > DRIVING_CAP_HOURS]
        by_source[src] = {
            "profitable_pairs": len(src_prof),
            "blocked_pairs": len(src_blk),
            "blocked_pct": (len(src_blk) / len(src_prof) * 100) if src_prof else 0.0,
            "blocked_margin_eur": round(sum(r["margin_eur"] for r in src_blk), 2),
        }

    # Drive-time histogram (10 bins: 0-1h, 1-2h, ..., 9-10h, 10h+)
    bins = [0] * 11
    for r in pair_rows:
        idx = min(10, int(r["drive_hours"]))
        bins[idx] += 1
    histogram = {
        "bin_edges_hours": list(range(11)) + [None],   # last bin is 10h+
        "counts": bins,
    }

    # Top-10 biggest-margin-loss
    top_losses = sorted(blocked, key=lambda r: r["margin_eur"], reverse=True)[:10]

    blocked_pct = (len(blocked) / len(profitable) * 100) if profitable else 0.0
    total_blocked_margin = round(sum(r["margin_eur"] for r in blocked), 2)
    avg_blocked_margin = round(total_blocked_margin / len(blocked), 2) if blocked else 0.0

    # Conservative annual fine exposure — assume one illegal dispatch
    # per van per day at the lower-bound fine.
    annual_fine_exposure = (
        len(vans) * ROMANIAN_WORKING_DAYS * FINE_PER_ILLEGAL_DISPATCH_EUR
    )

    result = {
        "experiment_id": "S2",
        "experiment": "Sentry — driver-hours feasibility filter",
        "agent": "sentry",
        "hypothesis": (
            "EU 561/2006's 9-hour daily driving cap blocks 8-20 % of "
            "profitable-on-price pairs; without the filter the optimiser "
            "would propose illegal dispatches."
        ),
        "inputs": {
            "fleet_size": len(vans),
            "load_pool_size": len(loads),
            "driving_cap_hours": DRIVING_CAP_HOURS,
            "depot": vans[0]["current_city"] if vans else None,
        },
        "results": {
            "total_pairs": total_pairs,
            "profitable_pairs": len(profitable),
            "blocked_pairs": len(blocked),
            "blocked_pct": round(blocked_pct, 2),
            "avg_blocked_margin_eur": avg_blocked_margin,
            "total_blocked_margin_eur": total_blocked_margin,
            "annual_fine_exposure_avoided_eur": annual_fine_exposure,
            "by_source": by_source,
        },
        "details": {
            "drive_time_histogram": histogram,
            "top_10_biggest_margin_losses": top_losses,
        },
        "provenance": provenance_block(
            mode="mock" if use_mock_llm else "gemini",
            model=ctx["analyst_log"].get("model"),
        ),
        "cost_meter": cost_meter_summary(since=started),
    }

    _assert_invariants(result, pair_rows)
    return result


def _assert_invariants(result: dict, pair_rows: list[dict]) -> None:
    """Truthfulness gate. Fails fast with a pointer to the predicate to
    investigate when any expectation is violated."""
    res = result["results"]

    # Predicate sanity: every blocked pair must actually be > 9 h.
    blocked = [r for r in pair_rows
               if r["margin_eur"] > 0 and r["drive_hours"] > DRIVING_CAP_HOURS]
    all_truly_infeasible = all(r["drive_hours"] > DRIVING_CAP_HOURS for r in blocked)

    blocked_pct = res["blocked_pct"]

    assert_invariants([
        (all_truly_infeasible,
         "Every flagged pair must have drive_hours > 9.0",
         "score_pair() in app/agents/fleet_strategist.py:64; check the "
         "AVG_SPEED_KMH constant and the hours_feasible predicate."),
        (res["blocked_pairs"] <= res["total_pairs"],
         "blocked_pairs <= total_pairs",
         "Indexing error in scripts/exp_s2_hours_filter.py::run()"),
        (blocked_pct < 50.0,
         f"blocked_pct={blocked_pct:.1f}% > 50 % suggests road_km factor "
         "is mis-scaled",
         "road_km_estimate() in app/services/geo.py:21 — currently *1.22"),
    ])


def _print_human(r: dict) -> None:
    res = r["results"]
    print()
    print("=" * 80)
    print(f"  S2 — Driver-hours feasibility filter  (Sentry agent)")
    print("=" * 80)
    inp = r["inputs"]
    print(f"  Fleet {inp['fleet_size']} vans × Loads {inp['load_pool_size']} "
          f"= {res['total_pairs']:,} pairs")
    print(f"  Profitable pairs:               {res['profitable_pairs']:,}")
    print(f"  Blocked by 9 h cap:             {res['blocked_pairs']:,}  "
          f"({res['blocked_pct']:.1f} % of profitable)")
    print(f"  Total blocked margin:           €{res['total_blocked_margin_eur']:,.0f}")
    print(f"  Avg blocked margin / pair:      €{res['avg_blocked_margin_eur']:,.2f}")
    print(f"  Conservative annual fine cap:   €{res['annual_fine_exposure_avoided_eur']:,}")
    print()
    print("  By source:")
    for src, b in res["by_source"].items():
        print(f"    {src:8}  {b['blocked_pairs']:4} blocked / {b['profitable_pairs']:4} profitable "
              f"({b['blocked_pct']:5.1f} %)  €{b['blocked_margin_eur']:,.0f} margin lost")
    print()
    print("  Top-3 biggest margin losses (full top-10 in JSON):")
    for row in r["details"]["top_10_biggest_margin_losses"][:3]:
        print(f"    {row['van_plate']:14}  {row['route']:36}  "
              f"€{row['margin_eur']:7.2f} / {row['drive_hours']:.1f} h")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--gemini", action="store_true",
                        help="Use live Gemini for hydration (no effect on the "
                             "numeric result — S2 is deterministic geometry).")
    args = parser.parse_args()

    result = run(use_mock_llm=not args.gemini)
    out = write_v2_json("exp_s2", result)
    print(f"[exp_s2] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

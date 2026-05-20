"""Shared helpers for converting the scraped 123cargo Frigo dataset
into shapes our planner can consume.

Two callers use this module:

  1. The admin API (`app/api/admin.py::import_123cargo`) — writes
     LoadRequest rows to PostgreSQL so the dispatcher UI can plan
     against real freight.
  2. The 123cargo experiment scripts (`scripts/exp_r{1..4}_*.py`) —
     hydrate `LoadSnapshot` dicts directly in memory and feed them
     to `plan_fleet_routes()`, bypassing the database entirely.

Both paths use the same cargo-type heuristic + per-cargo temperature
defaults, so a load that the admin endpoint persists looks identical
to a load the experiment script builds in memory.

The dataset itself (`backend/data/123cargo/frigo_loads.json`) is
produced by `scripts/scrape_123cargo.py` from the user's own
authenticated browser session.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATASET_PATH = BACKEND_DIR / "data" / "123cargo" / "frigo_loads.json"


def dataset_exists() -> bool:
    return DATASET_PATH.exists()


def load_dataset() -> dict[str, Any]:
    """Read + parse the scraped Frigo dataset. Raises FileNotFoundError
    if the file is missing (caller decides how to surface that — 404 in
    the API, fail-fast in the experiment scripts)."""
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"123cargo dataset not found at {DATASET_PATH}. "
            f"Run `python -m scripts.scrape_123cargo` to produce one."
        )
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def guess_cargo_type(row: dict[str, Any]) -> str:
    """Map a 123cargo load to one of our cargo-type enums via weight.

    The 123cargo entry only carries the temperature-controlled flag —
    not the exact food class — so we make a heuristic guess:

      heavy (≥ 10 t)  → "dairy"   (UHT pallets, the most common
                                    temp-controlled bulk freight)
      medium (3-10 t) → "produce" (mixed vegetables / fruit)
      light (< 3 t)   → "pharma"  (high-value small loads, a common
                                    Frigo niche)

    The dispatcher UI's manual load form lets the operator override
    this if a specific cargo class matters for a test scenario.
    """
    w = int(row.get("weight_kg") or 0)
    if w >= 10_000:
        return "dairy"
    if w >= 3_000:
        return "produce"
    return "pharma"


def derive_price_eur(row: dict[str, Any]) -> float:
    """Compute a per-load EUR price that's plausible for the optimiser.

    123cargo rows often have no quoted price (the broker hides it until
    you contact them). For those rows we synthesise from the published
    route distance at €2/km — same default the random load generator
    uses, so the per-load economics stay consistent across data sources.
    Minimum floor of €150 so a tiny intra-city run still has positive
    margin once 0.85 €/km cost is subtracted.
    """
    return max(
        float(row.get("price_eur") or 0),
        float(row.get("route_distance_km") or 0) * 2.0,
        150.0,
    )


# Mirror the cargo-defaults table in `services.random_fixtures` so a
# 123cargo load behaves identically to a randomly-generated load in the
# Analyst's compliance reasoning.
def _cargo_defaults() -> dict[str, dict[str, Any]]:
    # Late import avoids circular dep on package init
    from app.services.random_fixtures import _CARGO_DEFAULTS
    return _CARGO_DEFAULTS


def row_to_snapshot(
    row: dict[str, Any],
    *,
    snapshot_id: int,
    base_time: datetime | None = None,
) -> dict[str, Any]:
    """Convert a single scraped row → a `LoadSnapshot`-shaped dict.

    Used by the experiment scripts which need in-memory snapshots, not
    DB rows. Output matches `app/agents/state.py::LoadSnapshot`.

    `snapshot_id` should be unique within the experiment run (the
    scraped 123cargo IDs are strings — `BM-…` — but our planner keys
    by integer IDs, so the caller assigns them).
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc).replace(
            hour=8, minute=0, second=0, microsecond=0,
        )
    cargo = guess_cargo_type(row)
    defaults = _cargo_defaults()[cargo]

    # Spread pickup windows 2-12 h after `base_time` so different loads
    # don't all start at the same minute. Deterministic per-load (hash of
    # the 123cargo id) so re-runs produce the same windows.
    offset_h = 2 + (abs(hash(row["id"])) % 11)
    win_start = base_time + timedelta(hours=offset_h)
    win_end = win_start + timedelta(hours=8)

    return {
        "id":                       snapshot_id,
        "shipper_name":             f"123cargo {row['id']}",
        "cargo_type":               cargo,
        "cargo_description":        f"Real freight from 123cargo.eu — "
                                     f"{row['raw_source']} → {row['raw_destination']}",
        "temp_min_celsius":         defaults["temp"][0],
        "temp_max_celsius":         defaults["temp"][1],
        "requires_pharma_logger":   defaults["logger"],
        "forbidden_prior_cargo":    defaults["fpc"],
        "pickup_city":              row["source_city"],
        "pickup_lat":               float(row["source_lat"]),
        "pickup_lon":               float(row["source_lng"]),
        "delivery_city":            row["destination_city"],
        "delivery_lat":             float(row["destination_lat"]),
        "delivery_lon":             float(row["destination_lng"]),
        "pickup_window_start":      win_start.isoformat(),
        "pickup_window_end":        win_end.isoformat(),
        "weight_kg":                float(row.get("weight_kg") or 1000),
        "price_eur":                derive_price_eur(row),
        "status":                   "available",
        "source":                   "broker",
        # Free-form metadata the experiments use for traceability
        "_origin_123cargo_id":      row["id"],
        "_route_distance_km":       int(row.get("route_distance_km") or 0),
    }


def all_snapshots(*, base_time: datetime | None = None) -> list[dict[str, Any]]:
    """Return every Frigo load in the dataset as a LoadSnapshot dict.
    Used by R-experiments that consume the whole dataset, not a subset."""
    data = load_dataset()
    rows = list(data.get("loads", []))
    return [
        row_to_snapshot(r, snapshot_id=20_000 + i, base_time=base_time)
        for i, r in enumerate(rows)
    ]

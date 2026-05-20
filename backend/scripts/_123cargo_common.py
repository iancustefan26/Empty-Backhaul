"""Shared utilities for the 123cargo R-series experiments.

Why this lives separately from `_exp_common.py`: the v2 suite writes to
`docs/experiments_v2/`; the R-series writes to
`docs/experiments_123cargo/`. Same patterns (assert_invariants,
provenance_block) but different output dirs, so a clean split avoids
accidental pollution.

Public surface:
  - EXP_DIR, FIG_DIR  — output directories
  - DEPOT_CITIES      — top-4 depot cities by load-origin density,
                        auto-derived once from the dataset
  - load_origin_counts() — diagnostic helper for the depot priority
  - build_homogeneous_fleet(...)  — synthesise N vans at K depots
  - write_json(...), provenance_block(...) — mirror of _exp_common
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.data.romania_cities import ROMANIA_CITIES, city  # noqa: E402
from app.services import load_123cargo as l123c  # noqa: E402

EXP_DIR = BACKEND_DIR / "docs" / "experiments_123cargo"
FIG_DIR = BACKEND_DIR / "docs" / "figures" / "experiments_123cargo"


# ---------------------------------------------------------------------------
# Depot priority (auto-derived from dataset, no hand-tuning)
# ---------------------------------------------------------------------------

def load_origin_counts() -> Counter:
    """Counter mapping cleaned source-city name → load count.

    Cities NOT in `ROMANIA_CITIES` get dropped silently (we need known
    lat/lon to base a depot there); the R-series only ever picks from
    cities that have both data presence AND a coordinate row.
    """
    data = l123c.load_dataset()
    counts: Counter = Counter()
    for row in data.get("loads", []):
        c = row.get("source_city", "").strip()
        if c in ROMANIA_CITIES:
            counts[c] += 1
    return counts


def _priority_depots() -> list[str]:
    """Top-N depot cities, ordered by load-origin frequency, falling
    back to a sensible default order if the dataset is too sparse."""
    counts = load_origin_counts()
    if not counts:
        return ["Cluj-Napoca", "Bucuresti", "Timisoara", "Constanta"]
    by_count = [c for c, _ in counts.most_common()]
    # Always include Cluj as a fallback (depot of the synthetic seed)
    # so single-depot baselines stay consistent across experiments
    for must in ("Cluj-Napoca", "Bucuresti", "Timisoara", "Constanta"):
        if must not in by_count and must in ROMANIA_CITIES:
            by_count.append(must)
    return by_count[:4]


DEPOT_CITIES = _priority_depots()  # evaluated once at import


# ---------------------------------------------------------------------------
# Fleet builder
# ---------------------------------------------------------------------------

def build_homogeneous_fleet(
    *,
    n_vans: int,
    depot_cities: list[str] | None = None,
    id_start: int = 30_000,
) -> list[dict]:
    """Synthesise N vans split as evenly as possible across the given depots.

    Capability mix is a fixed cycle that looks like a realistic small
    Romanian reefer SMB (multi_temp × 2, chilled × 2, frozen, pharma+logger,
    ambient) repeated as needed. `last_cargo='clean'` everywhere so
    compliance is NOT the bottleneck — the R-experiments measure
    routing + chaining, not regulatory blocking.

    `depot_cities` defaults to a single Cluj depot. For multi-depot
    configurations, pass a list (e.g. `["Cluj-Napoca", "Bucuresti"]`).
    Vans are assigned to depots round-robin.
    """
    if depot_cities is None:
        depot_cities = ["Cluj-Napoca"]
    if not depot_cities:
        raise ValueError("depot_cities must be non-empty")

    capability_cycle = [
        ("multi_temp", False),
        ("chilled", False),
        ("multi_temp", False),
        ("chilled", False),
        ("frozen", False),
        ("pharma_2_8", True),
        ("ambient", False),
    ]

    vans = []
    for i in range(n_vans):
        depot = depot_cities[i % len(depot_cities)]
        c = city(depot)
        capability, has_logger = capability_cycle[i % len(capability_cycle)]
        vans.append({
            "id":                       id_start + i,
            "plate_number":             f"VAN-{i+1:03d}-{depot[:3].upper()}",
            "carrier_name":             "R-series test carrier",
            "temp_capability":          capability,
            "last_cargo":               "clean",
            "has_pharma_logger":        has_logger,
            "remaining_driving_hours":  9.0,
            "status":                   "empty",
            "current_city":             depot,
            "home_base_city":           depot,
            "lat":                      c.lat,
            "lon":                      c.lon,
            "wash_certificates":        [],
        })
    return vans


# ---------------------------------------------------------------------------
# Output / provenance
# ---------------------------------------------------------------------------

def write_json(experiment_id: str, payload: dict) -> Path:
    out = EXP_DIR / f"{experiment_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    return out


def current_git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BACKEND_DIR, stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def provenance_block(*, dataset_meta: dict | None = None) -> dict:
    """Standard provenance block embedded in every R-series JSON."""
    return {
        "completed_at":       datetime.now(timezone.utc).isoformat(),
        "git_sha":            current_git_sha(),
        "dataset":            "123cargo.eu Frigo snapshot",
        "dataset_scraped_at": (dataset_meta or {}).get("scraped_at_utc"),
        "dataset_size":       (dataset_meta or {}).get("frigo_count"),
        "depot_priority":     list(DEPOT_CITIES),
    }


# ---------------------------------------------------------------------------
# Truthfulness gate (mirror of _exp_common.assert_invariants)
# ---------------------------------------------------------------------------

def assert_invariants(checks: list[tuple[bool, str, str]]) -> None:
    failed = [(label, where) for ok, label, where in checks if not ok]
    if not failed:
        return
    print("\n=== INVARIANT FAILURES ===", file=sys.stderr)
    for label, where in failed:
        print(f"  ✗ {label}", file=sys.stderr)
        print(f"      investigate: {where}", file=sys.stderr)
    print("==========================\n", file=sys.stderr)
    raise SystemExit(1)

"""Loader for the Li & Lim PDPTW benchmark instances.

Downloads instances from the `zhu-he/pdptw-data` GitHub mirror (which
itself daily-syncs the canonical SINTEF dataset) and converts them into
TruckSnapshot / LoadSnapshot dicts that our existing Sentry → Analyst →
Strategist pipeline can consume without touching Supabase.

Instance file format (tab-separated, no header text):

    line 1                  K   Q   S         (vehicles, capacity, speed)
    lines 2..N (per task)   id  x  y  demand  ready_time  due_date
                            service_time  pickup_idx  delivery_idx

  - Task 0 is the depot.
  - A pickup row has `pickup_idx = 0` and `delivery_idx > 0` (pointing
    at the matching delivery task).
  - A delivery row has `pickup_idx > 0` and `delivery_idx = 0`.
  - `demand` is positive at the pickup, negative (matching magnitude)
    at the delivery.

We convert each pickup→delivery PAIR into one LoadSnapshot. A
100-node instance gives 1 depot + ~50 pickup-delivery pairs.

Reference: Li, H. & Lim, A. (2003). A metaheuristic for the pickup and
delivery problem with time windows. *International Journal on AI Tools*,
12(2):173-186.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXTERNAL_DATA_DIR = BACKEND_DIR / ".external_data" / "lilim"

# Canonical mirror of the SINTEF benchmark, kept daily-synced.
DOWNLOAD_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/zhu-he/pdptw-data/master/{size}/{name}.txt"
)

# Romania-anchored coordinate mapping. Li & Lim coordinates are abstract
# Euclidean km in a roughly [0, 100] × [0, 100] grid. We map them to fake
# WGS84 lat/lon centred on Cluj-Napoca so haversine_km (used downstream
# by score_pair) returns approximately the Euclidean distance.
BASE_LAT = 46.7712   # Cluj-Napoca
BASE_LON = 23.6236
KM_PER_DEG_LAT = 111.0
KM_PER_DEG_LON_AT_BASE = 77.0   # cos(46.77°) × 111


class _Task(TypedDict):
    task_no: int
    x: float
    y: float
    demand: float
    ready_time: int
    due_date: int
    service_time: int
    pickup_idx: int
    delivery_idx: int


class LilimInstance(TypedDict):
    name: str            # e.g. "lc101"
    size: int            # 100, 200, 400, …
    n_vehicles: int      # K from the header
    capacity: int        # Q from the header
    depot: _Task
    tasks: list[_Task]   # excludes the depot
    pickup_delivery_pairs: list[tuple[_Task, _Task]]


# ---------------------------------------------------------------------------
# Coordinate helpers (Euclidean km → fake Romanian lat/lon)
# ---------------------------------------------------------------------------

def _xy_to_latlon(x: float, y: float) -> tuple[float, float]:
    lat = BASE_LAT + (y - 50.0) / KM_PER_DEG_LAT
    lon = BASE_LON + (x - 50.0) / KM_PER_DEG_LON_AT_BASE
    return lat, lon


# ---------------------------------------------------------------------------
# File acquisition + parsing
# ---------------------------------------------------------------------------

def _instance_path(name: str, size: int) -> Path:
    return EXTERNAL_DATA_DIR / str(size) / f"{name}.txt"


def _download_if_missing(name: str, size: int) -> Path:
    out = _instance_path(name, size)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    url = DOWNLOAD_URL_TEMPLATE.format(size=size, name=name)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            out.write_bytes(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Could not download Li & Lim instance {name!r} from {url}: "
            f"HTTP {e.code}. Check the spelling (lowercase, three digits, "
            f"e.g. 'lc101') and the size folder ({size})."
        ) from e
    return out


def parse_instance(name: str, size: int = 100) -> LilimInstance:
    """Parse a Li & Lim instance file into an `LilimInstance`."""
    path = _download_if_missing(name, size)
    lines = [
        ln for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]

    # Header line: K Q S
    header = lines[0].split()
    n_vehicles = int(header[0])
    capacity = int(header[1])

    tasks: list[_Task] = []
    for raw in lines[1:]:
        cols = raw.split()
        if len(cols) < 9:
            continue
        tasks.append(_Task(
            task_no=int(cols[0]),
            x=float(cols[1]),
            y=float(cols[2]),
            demand=float(cols[3]),
            ready_time=int(cols[4]),
            due_date=int(cols[5]),
            service_time=int(cols[6]),
            pickup_idx=int(cols[7]),
            delivery_idx=int(cols[8]),
        ))

    if not tasks or tasks[0]["task_no"] != 0:
        raise ValueError(f"{name}: expected task 0 (depot) as the first row")

    depot = tasks[0]
    by_id = {t["task_no"]: t for t in tasks}

    # Pickups: pickup_idx == 0 AND delivery_idx > 0.
    pairs: list[tuple[_Task, _Task]] = []
    for t in tasks[1:]:
        if t["pickup_idx"] == 0 and t["delivery_idx"] > 0:
            dlv = by_id.get(t["delivery_idx"])
            if dlv is not None:
                pairs.append((t, dlv))

    return LilimInstance(
        name=name, size=size, n_vehicles=n_vehicles, capacity=capacity,
        depot=depot, tasks=tasks[1:], pickup_delivery_pairs=pairs,
    )


# ---------------------------------------------------------------------------
# Synthesis: build TruckSnapshot[] + LoadSnapshot[]
# ---------------------------------------------------------------------------

def synthesise_fixtures(
    instance: LilimInstance,
    *,
    price_eur_per_loaded_km: float = 5.0,
    base_time: datetime | None = None,
) -> tuple[list[dict], list[dict]]:
    """Convert an LilimInstance into (vans, loads) lists compatible with
    `hydrate(vans=..., loads=...)`.

    Design choices:

      * Vans are HOMOGENEOUS — all multi_temp + clean prior + pharma
        logger present. This makes every (van, load) pair compliant on
        the hard rules, so the experiment isolates the OPTIMIZATION
        engine, not the compliance pipeline. (Compliance is exercised
        by the other experiments — A1, S2.)
      * Loads inherit cargo_type "ambient_dry" + no forbidden_prior so
        the same compliance-passes invariant holds.
      * Price is synthesised at `price_eur_per_loaded_km × Euclidean km`
        between pickup and delivery so margin (= price − 0.85 × total_km)
        is positive on most pairs.
      * Pickup/delivery coordinates map to fake Cluj-anchored lat/lon
        via `_xy_to_latlon`, so the downstream haversine_km returns ≈
        Euclidean km.
      * Time windows are remapped: Li & Lim's integer ready/due units
        become minutes offset from a base wall-clock time.
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc).replace(
            hour=6, minute=0, second=0, microsecond=0,
        )

    # ----- Fleet (K homogeneous vans at the depot) -----
    depot_lat, depot_lon = _xy_to_latlon(instance["depot"]["x"], instance["depot"]["y"])
    depot_city = f"Lilim-{instance['name']}-depot"
    vans: list[dict] = []
    for i in range(instance["n_vehicles"]):
        vans.append({
            "id": 10_000 + i,
            "plate_number": f"LL-{instance['name'].upper()}-{i+1:02d}",
            "carrier_name": "Li & Lim PDPTW benchmark fleet",
            "temp_capability": "multi_temp",
            "last_cargo": "clean",
            "has_pharma_logger": True,
            "remaining_driving_hours": 24.0,   # Li & Lim instances ignore EU 561
            "status": "empty",
            "current_city": depot_city,
            "home_base_city": depot_city,
            "lat": depot_lat,
            "lon": depot_lon,
            "wash_certificates": [],
        })

    # ----- Loads (one per pickup-delivery pair) -----
    loads: list[dict] = []
    for k, (pu, dlv) in enumerate(instance["pickup_delivery_pairs"]):
        pu_lat, pu_lon = _xy_to_latlon(pu["x"], pu["y"])
        dlv_lat, dlv_lon = _xy_to_latlon(dlv["x"], dlv["y"])
        # Euclidean km of the loaded leg (matches what haversine_km
        # returns under our coordinate map, within rounding).
        loaded_km = ((dlv["x"] - pu["x"]) ** 2 + (dlv["y"] - pu["y"]) ** 2) ** 0.5
        # Window: 1 Li & Lim time-unit ≈ 1 minute.
        win_start = base_time + timedelta(minutes=int(pu["ready_time"]))
        win_end = base_time + timedelta(minutes=int(pu["due_date"]))
        loads.append({
            "id": 20_000 + pu["task_no"],
            "shipper_name": f"Li&Lim pair #{k+1} ({instance['name']})",
            "cargo_type": "ambient_dry",
            "cargo_description": f"PDPTW synthetic load — pickup task "
                                 f"{pu['task_no']}, delivery task {dlv['task_no']}",
            "temp_min_celsius": 5.0,
            "temp_max_celsius": 25.0,
            "requires_pharma_logger": False,
            "forbidden_prior_cargo": None,
            "pickup_city": f"LL-{pu['task_no']}",
            "delivery_city": f"LL-{dlv['task_no']}",
            "pickup_lat": pu_lat,
            "pickup_lon": pu_lon,
            "delivery_lat": dlv_lat,
            "delivery_lon": dlv_lon,
            "pickup_window_start": win_start.isoformat(),
            "pickup_window_end": win_end.isoformat(),
            "weight_kg": float(pu["demand"]),
            "price_eur": round(loaded_km * price_eur_per_loaded_km, 2),
            "status": "available",
            "source": "broker",
        })

    return vans, loads


# ---------------------------------------------------------------------------
# CLI: `python -m scripts.lilim_loader lc101 --size 100`
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Download + parse a Li & Lim PDPTW instance.")
    p.add_argument("name", help="e.g. lc101, lr101, lrc101, lc201 …")
    p.add_argument("--size", type=int, default=100,
                   help="Instance node count (100, 200, 400, 600, 800, 1000)")
    args = p.parse_args()

    inst = parse_instance(args.name, size=args.size)
    print(f"{args.name}  size={inst['size']}  vehicles={inst['n_vehicles']}  "
          f"capacity={inst['capacity']}  pairs={len(inst['pickup_delivery_pairs'])}",
          file=sys.stderr)
    vans, loads = synthesise_fixtures(inst)
    print(f"  → synthesised {len(vans)} vans + {len(loads)} loads", file=sys.stderr)


if __name__ == "__main__":
    main()

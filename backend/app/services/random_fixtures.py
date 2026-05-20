"""Random truck + load generators for the admin API.

The dispatcher console exposes a "Random N" button on the Fleet Manager
modal so the user can populate a test scenario quickly. Generators below
back those buttons. They produce VALID dict payloads matching the
Truck / LoadRequest model fields — no orphan keys, all enums in the
canonical set, coordinates resolved through `romania_cities.py`.

Generators do NOT touch the database. The admin API handler is what
persists.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.data.romania_cities import ROMANIA_CITIES

# Canonical enum sets — mirror what seed_data.py uses so the analyst's
# hard rules + RAG queries Just Work on random data.
TRUCK_CAPABILITIES = ("multi_temp", "chilled", "frozen", "pharma_2_8", "ambient")
TRUCK_LAST_CARGOES = (
    "clean", "dairy", "produce", "raw_meat", "raw_poultry",
    "pharma", "frozen", "chemicals",
)

CARGO_TYPES = (
    "pharma", "dairy", "produce", "raw_meat", "raw_poultry",
    "frozen_vegetables", "frozen_fish", "ambient_dry", "chemicals",
)

# Per-cargo defaults so random loads make compliance sense.
_CARGO_DEFAULTS: dict[str, dict[str, Any]] = {
    "pharma":            {"temp": (2.0, 8.0),    "logger": True,  "fpc": "chemicals,raw_meat,raw_poultry"},
    "dairy":             {"temp": (2.0, 7.0),    "logger": False, "fpc": "raw_meat,raw_poultry,chemicals"},
    "produce":           {"temp": (4.0, 10.0),   "logger": False, "fpc": "raw_meat,raw_poultry,chemicals"},
    "raw_meat":          {"temp": (0.0, 4.0),    "logger": False, "fpc": "chemicals"},
    "raw_poultry":       {"temp": (0.0, 4.0),    "logger": False, "fpc": "chemicals"},
    "frozen_vegetables": {"temp": (-25.0, -18.0), "logger": False, "fpc": None},
    "frozen_fish":       {"temp": (-22.0, -18.0), "logger": False, "fpc": "chemicals"},
    "ambient_dry":       {"temp": (5.0, 25.0),   "logger": False, "fpc": "chemicals"},
    "chemicals":         {"temp": (5.0, 30.0),   "logger": False, "fpc": None},
}

# Shippers — anonymised, generated on demand. Real Romanian names mixed
# with placeholders so the demo looks plausible.
_SHIPPER_POOL = (
    "Antibiotice Iasi", "Polisano", "Cris-Tim", "Albalact", "Napolact",
    "Bonduelle Romania", "Macromex", "Negro 2000", "AgriFresh Moldova",
    "Hortifruct Cluj", "Boromir", "OMV Petrom", "Avicarvil",
    "Dacia Renault Logistics", "Aldis", "Olympus", "Hochland Romania",
    "Selgros Romania",
)

DEPOT = "Cluj-Napoca"


def _random_city(exclude: str | None = None) -> str:
    names = [n for n in ROMANIA_CITIES.keys() if n != exclude]
    return random.choice(names)


def random_truck_payload(
    *,
    plate_seed: int | None = None,
) -> dict[str, Any]:
    """Return a dict suitable for `Truck(**payload)`.

    Plate is generated as CJ-{NNN}-CRL with N either provided
    (`plate_seed`) or random. Coordinates default to the Cluj depot
    so the truck starts somewhere sensible.
    """
    suffix = plate_seed if plate_seed is not None else random.randint(600, 999)
    plate = f"CJ-{suffix:03d}-CRL"

    capability = random.choice(TRUCK_CAPABILITIES)
    last_cargo = random.choice(TRUCK_LAST_CARGOES)

    # Pharma capability needs a logger most of the time
    has_logger = capability == "pharma_2_8" or (random.random() < 0.15)

    return {
        "plate_number": plate,
        "carrier_name": "Cluj Reefer Logistics",
        "temp_capability": capability,
        "last_cargo": last_cargo,
        "has_pharma_logger": has_logger,
        "remaining_driving_hours": 9.0,
        "status": "empty",
        "home_base_city": DEPOT,
        "current_city": DEPOT,
    }


def random_load_payload(
    *,
    base_time: datetime | None = None,
    cargo_type: str | None = None,
    pickup_city: str | None = None,
    delivery_city: str | None = None,
) -> dict[str, Any]:
    """Return a dict suitable for `LoadRequest(**payload)`.

    All overrides are optional. With no overrides, a fully-random load
    is built using realistic Romanian cities, sensible cargo defaults,
    and a pickup window 2-8 hours from `base_time` (default: now).
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc).replace(
            hour=8, minute=0, second=0, microsecond=0,
        )
    if cargo_type is None:
        cargo_type = random.choice(CARGO_TYPES)
    if pickup_city is None:
        pickup_city = _random_city()
    if delivery_city is None:
        delivery_city = _random_city(exclude=pickup_city)

    defaults = _CARGO_DEFAULTS[cargo_type]
    weight_kg = random.randint(2000, 18000)
    # Price scales loosely with weight + a cargo-class premium
    cargo_multiplier = {
        "pharma": 0.20, "raw_meat": 0.07, "raw_poultry": 0.06,
        "dairy": 0.06, "produce": 0.05, "frozen_fish": 0.07,
        "frozen_vegetables": 0.05, "ambient_dry": 0.03, "chemicals": 0.04,
    }[cargo_type]
    price_eur = int(weight_kg * cargo_multiplier + random.randint(200, 500))

    hours_offset = random.randint(2, 8)
    window_hours = random.randint(5, 10)
    win_start = base_time + timedelta(hours=hours_offset)
    win_end = win_start + timedelta(hours=window_hours)

    return {
        "shipper_name": random.choice(_SHIPPER_POOL),
        "cargo_type": cargo_type,
        "cargo_description": f"Random {cargo_type} load",
        "temp_min_celsius": defaults["temp"][0],
        "temp_max_celsius": defaults["temp"][1],
        "requires_pharma_logger": defaults["logger"],
        "forbidden_prior_cargo": defaults["fpc"],
        "pickup_city": pickup_city,
        "delivery_city": delivery_city,
        "pickup_window_start": win_start,
        "pickup_window_end": win_end,
        "weight_kg": weight_kg,
        "price_eur": price_eur,
        "status": "available",
        "source": "broker",
    }

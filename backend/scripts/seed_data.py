"""Seed the Supabase database with synthetic Romanian backhaul fixtures.

Run from /backend with the venv active and SUPABASE_DATABASE_URL set:

    python -m scripts.seed_data --reset       # wipe + reseed
    python -m scripts.seed_data --dry-run     # validate fixtures, don't touch DB
    python -m scripts.seed_data               # seed only if tables are empty

The fixtures are crafted to exercise the Phase 3 agents:
  * raw_meat trucks with/without a wash certificate (HACCP gate)
  * pharma 2-8 °C loads requiring trucks with a calibrated logger
  * frozen vs. chilled vs. ambient capability mismatches
  * route alignments where the optimal pick is not the closest pickup
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Make /backend importable when run as `python -m scripts.seed_data`.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from geoalchemy2.elements import WKTElement
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.data.romania_cities import wkt_point
from app.models import LoadRequest, RouteHistory, Truck, WashCertificate


# Anchor demo time so fixtures are deterministic across runs.
NOW = datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc)
TOMORROW_06 = (NOW + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)


def _pt(city_name: str) -> WKTElement:
    return WKTElement(wkt_point(city_name), srid=4326)


# ---------------------------------------------------------------------------
# 10 trucks ending deliveries in CJ / TM / IS / CT / SB, returning to B / OR.
# ---------------------------------------------------------------------------
def truck_fixtures() -> list[dict[str, Any]]:
    return [
        # --- Cluj-Napoca → Bucuresti --------------------------------------
        dict(
            plate_number="B-101-CBO", carrier_name="Carpatica Logistics",
            current_city="Cluj-Napoca", home_base_city="Bucuresti",
            temp_capability="chilled", last_cargo="dairy",
            has_pharma_logger=False, remaining_driving_hours=8.0, status="empty",
        ),
        dict(
            plate_number="B-202-CBO", carrier_name="Pharma Express RO",
            current_city="Cluj-Napoca", home_base_city="Bucuresti",
            temp_capability="pharma_2_8", last_cargo="pharma",
            has_pharma_logger=True, remaining_driving_hours=7.5, status="empty",
        ),
        # --- Timisoara → Oradea -------------------------------------------
        dict(
            plate_number="OR-303-CBO", carrier_name="Banat Frig",
            current_city="Timisoara", home_base_city="Oradea",
            temp_capability="frozen", last_cargo="frozen",
            has_pharma_logger=False, remaining_driving_hours=6.0, status="empty",
        ),
        dict(
            plate_number="OR-404-CBO", carrier_name="Multitemp Vest",
            current_city="Timisoara", home_base_city="Oradea",
            temp_capability="multi_temp", last_cargo="raw_meat",
            has_pharma_logger=False, remaining_driving_hours=5.5, status="empty",
        ),
        # --- Iasi → Bucuresti ---------------------------------------------
        dict(
            plate_number="B-505-CBO", carrier_name="Moldova Cold Chain",
            current_city="Iasi", home_base_city="Bucuresti",
            temp_capability="chilled", last_cargo="produce",
            has_pharma_logger=False, remaining_driving_hours=7.0, status="empty",
        ),
        dict(
            plate_number="B-606-CBO", carrier_name="Pharma Express RO",
            current_city="Iasi", home_base_city="Bucuresti",
            temp_capability="pharma_2_8", last_cargo="pharma",
            has_pharma_logger=True, remaining_driving_hours=4.5, status="loaded",
        ),
        # --- Constanta → Bucuresti ----------------------------------------
        dict(
            plate_number="B-707-CBO", carrier_name="Pontica Frigo",
            current_city="Constanta", home_base_city="Bucuresti",
            temp_capability="frozen", last_cargo="frozen",
            has_pharma_logger=False, remaining_driving_hours=8.5, status="empty",
        ),
        dict(
            plate_number="B-808-CBO", carrier_name="Pontica Frigo",
            current_city="Constanta", home_base_city="Bucuresti",
            temp_capability="multi_temp", last_cargo="clean",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        # --- Sibiu → Bucuresti / Oradea -----------------------------------
        dict(
            # last_cargo=raw_meat WITHOUT wash cert -> Analyst should reject
            # any non-meat food-grade load until sanitisation is performed.
            plate_number="B-909-CBO", carrier_name="Transilvania Reefer",
            current_city="Sibiu", home_base_city="Bucuresti",
            temp_capability="chilled", last_cargo="raw_meat",
            has_pharma_logger=False, remaining_driving_hours=6.5, status="empty",
        ),
        dict(
            plate_number="OR-010-CBO", carrier_name="Crisana Logistic",
            current_city="Sibiu", home_base_city="Oradea",
            temp_capability="ambient", last_cargo="chemicals",
            has_pharma_logger=False, remaining_driving_hours=4.0, status="returning",
        ),
    ]


# ---------------------------------------------------------------------------
# 20 backhaul loads with realistic Romanian routes + temperature regimes.
# ---------------------------------------------------------------------------
def load_fixtures() -> list[dict[str, Any]]:
    base = TOMORROW_06

    def window(hours_offset: int, window_hours: int = 8) -> tuple[datetime, datetime]:
        start = base + timedelta(hours=hours_offset)
        return start, start + timedelta(hours=window_hours)

    return [
        # 1. Pharma Cluj -> Bucuresti (perfect for truck #2)
        dict(
            shipper_name="Antibiotice Iasi",
            cargo_type="pharma", cargo_description="Antibiotice 2-8°C palletised",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Cluj-Napoca", delivery_city="Bucuresti",
            window=window(2, 6), weight_kg=4500, price_eur=1850,
        ),
        # 2. Pharma Sibiu -> Bucuresti (only truck with logger near Sibiu wins)
        dict(
            shipper_name="Polisano",
            cargo_type="pharma", cargo_description="Vaccine cold-chain shipment",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Sibiu", delivery_city="Bucuresti",
            window=window(4, 5), weight_kg=2200, price_eur=1600,
        ),
        # 3. Raw poultry Timisoara -> Oradea (truck #3/#4 route alignment)
        dict(
            shipper_name="Avicola Banat",
            cargo_type="raw_poultry", cargo_description="Carcase pui refrigerate",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Timisoara", delivery_city="Oradea",
            window=window(3, 8), weight_kg=8500, price_eur=620,
        ),
        # 4. Raw meat Cluj -> Brasov
        dict(
            shipper_name="Cris-Tim",
            cargo_type="raw_meat", cargo_description="Carne porc semicarcase",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Brasov",
            window=window(5, 6), weight_kg=11000, price_eur=780,
        ),
        # 5. Dairy Sibiu -> Bucuresti (perfect route for truck #9 BUT blocked
        # by HACCP because truck #9's last cargo was raw_meat without wash cert)
        dict(
            shipper_name="Albalact",
            cargo_type="dairy", cargo_description="Lapte UHT + iaurt",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Sibiu", delivery_city="Bucuresti",
            window=window(6, 8), weight_kg=9000, price_eur=720,
        ),
        # 6. Dairy Cluj -> Pitesti
        dict(
            shipper_name="Napolact",
            cargo_type="dairy", cargo_description="Branzeturi maturate",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Pitesti",
            window=window(7, 8), weight_kg=6500, price_eur=690,
        ),
        # 7. Frozen veg Timisoara -> Oradea (perfect for truck #3)
        dict(
            shipper_name="Bonduelle Romania",
            cargo_type="frozen_vegetables", cargo_description="Mazare + porumb -22°C",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo=None,
            pickup_city="Timisoara", delivery_city="Oradea",
            window=window(2, 10), weight_kg=14000, price_eur=540,
        ),
        # 8. Frozen veg Constanta -> Bucuresti (perfect for truck #7)
        dict(
            shipper_name="Macromex",
            cargo_type="frozen_vegetables", cargo_description="Legume IQF",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo=None,
            pickup_city="Constanta", delivery_city="Bucuresti",
            window=window(3, 9), weight_kg=18000, price_eur=720,
        ),
        # 9. Frozen fish Constanta -> Bucuresti (alt to load #8)
        dict(
            shipper_name="Negro 2000",
            cargo_type="frozen_fish", cargo_description="Hamsie congelata blocata",
            temp_min_celsius=-22.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Constanta", delivery_city="Bucuresti",
            window=window(8, 8), weight_kg=12000, price_eur=860,
        ),
        # 10. Produce Iasi -> Bucuresti (perfect for truck #5)
        dict(
            shipper_name="AgriFresh Moldova",
            cargo_type="produce", cargo_description="Mere + pere ambalate",
            temp_min_celsius=4.0, temp_max_celsius=12.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Iasi", delivery_city="Bucuresti",
            window=window(4, 10), weight_kg=10500, price_eur=640,
        ),
        # 11. Produce Cluj -> Sibiu
        dict(
            shipper_name="Hortifruct Cluj",
            cargo_type="produce", cargo_description="Salata + spanac in lazi",
            temp_min_celsius=4.0, temp_max_celsius=10.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Sibiu",
            window=window(6, 6), weight_kg=4200, price_eur=380,
        ),
        # 12. Ambient dry Iasi -> Bucuresti
        dict(
            shipper_name="Boromir",
            cargo_type="ambient_dry", cargo_description="Faina + paste",
            temp_min_celsius=-5.0, temp_max_celsius=35.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Iasi", delivery_city="Bucuresti",
            window=window(2, 12), weight_kg=22000, price_eur=520,
        ),
        # 13. Chemicals Constanta -> Ploiesti (port -> refinery)
        dict(
            shipper_name="OMV Petrom",
            cargo_type="chemicals", cargo_description="Aditivi industriali ne-periculosi",
            temp_min_celsius=0.0, temp_max_celsius=30.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo=None,
            pickup_city="Constanta", delivery_city="Ploiesti",
            window=window(5, 10), weight_kg=20000, price_eur=480,
        ),
        # 14. Pharma Iasi -> Bucuresti
        dict(
            shipper_name="Antibiotice Iasi",
            cargo_type="pharma", cargo_description="Insulina 2-8°C",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Iasi", delivery_city="Bucuresti",
            window=window(6, 6), weight_kg=1800, price_eur=2100,
        ),
        # 15. Dairy Timisoara -> Arad (truck #4 OK *only because* it has a wash cert)
        dict(
            shipper_name="Hochland Romania",
            cargo_type="dairy", cargo_description="Branza topita",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Timisoara", delivery_city="Arad",
            window=window(4, 8), weight_kg=5200, price_eur=320,
        ),
        # 16. Raw poultry Sibiu -> Bucuresti (truck #9 raw_meat -> raw_poultry OK)
        dict(
            shipper_name="Avicarvil",
            cargo_type="raw_poultry", cargo_description="Pulpe pui refrigerate",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Sibiu", delivery_city="Bucuresti",
            window=window(7, 7), weight_kg=8800, price_eur=610,
        ),
        # 17. Frozen veg Cluj -> Oradea
        dict(
            shipper_name="Macromex",
            cargo_type="frozen_vegetables", cargo_description="Cartofi prajiti IQF",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo=None,
            pickup_city="Cluj-Napoca", delivery_city="Oradea",
            window=window(3, 9), weight_kg=15500, price_eur=580,
        ),
        # 18. Ambient dry Constanta -> Pitesti
        dict(
            shipper_name="Dacia Renault Logistics",
            cargo_type="ambient_dry", cargo_description="Piese auto ambalate",
            temp_min_celsius=-5.0, temp_max_celsius=40.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Constanta", delivery_city="Pitesti",
            window=window(8, 10), weight_kg=19000, price_eur=520,
        ),
        # 19. Raw meat Iasi -> Bacau
        dict(
            shipper_name="Aldis",
            cargo_type="raw_meat", cargo_description="Carne vita transat",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Iasi", delivery_city="Bacau",
            window=window(5, 5), weight_kg=7500, price_eur=410,
        ),
        # 20. Dairy Brasov -> Bucuresti
        dict(
            shipper_name="Olympus",
            cargo_type="dairy", cargo_description="Iaurt grecesc",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Brasov", delivery_city="Bucuresti",
            window=window(6, 8), weight_kg=4400, price_eur=360,
        ),
    ]


# ---------------------------------------------------------------------------
# A handful of wash certificates that unblock specific compliance scenarios.
# ---------------------------------------------------------------------------
def wash_cert_fixtures() -> list[dict[str, Any]]:
    return [
        # Truck #4 (Timisoara, last_cargo=raw_meat) was officially sanitised
        # in Arad yesterday -> Analyst can clear it for dairy / produce loads.
        dict(
            plate_number="OR-404-CBO",
            certificate_number="ANSVSA-TM-2026-04-29-0142",
            issued_at=NOW - timedelta(hours=18),
            valid_until=NOW + timedelta(days=3),
            wash_type="ansvsa_official",
            prior_cargo="raw_meat",
            issuing_facility="Statie spalare Arad — autorizatie ANSVSA TM-014",
            location_city="Arad",
        ),
        # Truck #10 (Sibiu, last_cargo=chemicals) had a deep wash on the way
        # back to Oradea, but ambient-only so its food-grade reuse is still
        # off-limits per HACCP — kept as a partial / flavour cert for realism.
        dict(
            plate_number="OR-010-CBO",
            certificate_number="WASH-VEST-2026-04-29-0007",
            issued_at=NOW - timedelta(hours=10),
            valid_until=NOW + timedelta(days=2),
            wash_type="deep",
            prior_cargo="chemicals",
            issuing_facility="Crisana Wash Station Oradea",
            location_city="Oradea",
        ),
    ]


# ---------------------------------------------------------------------------
# Validation -- runs in --dry-run too, so fixtures stay correct over time.
# ---------------------------------------------------------------------------
def _validate(trucks: list[dict], loads: list[dict], washes: list[dict]) -> None:
    plates = {t["plate_number"] for t in trucks}
    if len(plates) != len(trucks):
        raise ValueError("Duplicate truck plates in fixtures")
    if len(trucks) != 10:
        raise ValueError(f"Expected 10 trucks, got {len(trucks)}")
    if len(loads) != 20:
        raise ValueError(f"Expected 20 loads, got {len(loads)}")
    for w in washes:
        if w["plate_number"] not in plates:
            raise ValueError(f"Wash cert references unknown truck {w['plate_number']!r}")
    for ld in loads:
        if ld["temp_min_celsius"] > ld["temp_max_celsius"]:
            raise ValueError(f"Inverted temp range on load: {ld['cargo_description']!r}")


# ---------------------------------------------------------------------------
# DB writers
# ---------------------------------------------------------------------------
def _truncate_all(session) -> None:
    # CASCADE drops dependent FKs (route_history, wash_certificates).
    session.execute(text(
        "TRUNCATE TABLE route_history, wash_certificates, load_requests, trucks "
        "RESTART IDENTITY CASCADE"
    ))


def _insert_trucks(session, fixtures: list[dict]) -> dict[str, int]:
    plate_to_id: dict[str, int] = {}
    for f in fixtures:
        truck = Truck(
            plate_number=f["plate_number"],
            carrier_name=f["carrier_name"],
            temp_capability=f["temp_capability"],
            last_cargo=f["last_cargo"],
            has_pharma_logger=f["has_pharma_logger"],
            remaining_driving_hours=f["remaining_driving_hours"],
            status=f["status"],
            current_location=_pt(f["current_city"]),
            current_city=f["current_city"],
            home_base_city=f["home_base_city"],
        )
        session.add(truck)
        session.flush()
        plate_to_id[truck.plate_number] = truck.id
    return plate_to_id


def _insert_loads(session, fixtures: list[dict]) -> None:
    for f in fixtures:
        win_start, win_end = f["window"]
        session.add(LoadRequest(
            shipper_name=f["shipper_name"],
            cargo_type=f["cargo_type"],
            cargo_description=f["cargo_description"],
            temp_min_celsius=f["temp_min_celsius"],
            temp_max_celsius=f["temp_max_celsius"],
            requires_pharma_logger=f["requires_pharma_logger"],
            forbidden_prior_cargo=f["forbidden_prior_cargo"],
            pickup_location=_pt(f["pickup_city"]),
            pickup_city=f["pickup_city"],
            delivery_location=_pt(f["delivery_city"]),
            delivery_city=f["delivery_city"],
            pickup_window_start=win_start,
            pickup_window_end=win_end,
            weight_kg=f["weight_kg"],
            price_eur=f["price_eur"],
            status="available",
        ))


def _insert_washes(session, fixtures: list[dict], plate_to_id: dict[str, int]) -> None:
    for f in fixtures:
        session.add(WashCertificate(
            truck_id=plate_to_id[f["plate_number"]],
            certificate_number=f["certificate_number"],
            issued_at=f["issued_at"],
            valid_until=f["valid_until"],
            wash_type=f["wash_type"],
            prior_cargo=f["prior_cargo"],
            issuing_facility=f["issuing_facility"],
            location=_pt(f["location_city"]),
        ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def seed(*, reset: bool, dry_run: bool) -> None:
    trucks = truck_fixtures()
    loads = load_fixtures()
    washes = wash_cert_fixtures()
    _validate(trucks, loads, washes)

    if dry_run:
        print(f"[dry-run] Validated {len(trucks)} trucks, {len(loads)} loads, "
              f"{len(washes)} wash certificates. Nothing written.")
        return

    if SessionLocal is None:
        raise SystemExit(
            "SUPABASE_DATABASE_URL is not configured. Copy .env.example to .env "
            "and paste your Supabase URI before seeding."
        )

    with SessionLocal() as session:
        existing = session.execute(select(Truck)).first()
        if existing and not reset:
            print("Trucks already exist. Re-run with --reset to wipe and reseed.")
            return

        if reset:
            print("Truncating trucks / load_requests / route_history / wash_certificates...")
            _truncate_all(session)

        plate_to_id = _insert_trucks(session, trucks)
        _insert_loads(session, loads)
        _insert_washes(session, washes, plate_to_id)

        session.commit()

        truck_n = session.execute(select(Truck)).all()
        load_n = session.execute(select(LoadRequest)).all()
        wash_n = session.execute(select(WashCertificate)).all()
        route_n = session.execute(select(RouteHistory)).all()

    print("Seed complete:")
    print(f"  trucks            : {len(truck_n)}")
    print(f"  load_requests     : {len(load_n)}")
    print(f"  wash_certificates : {len(wash_n)}")
    print(f"  route_history     : {len(route_n)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Romanian backhaul fixtures.")
    parser.add_argument("--reset", action="store_true",
                        help="TRUNCATE all four tables before seeding.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate fixtures locally without touching the DB.")
    args = parser.parse_args()
    seed(reset=args.reset, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

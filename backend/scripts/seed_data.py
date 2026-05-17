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


# Anchor demo time relative to today so fixtures stay valid across re-seeds.
# Override with --base-date YYYY-MM-DD if you want a deterministic anchor (e.g. for
# reproducing an evaluation run).
NOW = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
TOMORROW_06 = (NOW + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)


def _pt(city_name: str) -> WKTElement:
    return WKTElement(wkt_point(city_name), srid=4326)


# ---------------------------------------------------------------------------
# 10 vans of a single Cluj-Napoca-based refrigerated transport company.
# Every van starts and must end the day back at the Cluj-Napoca depot.
# Capabilities, last_cargo, wash certs are deliberately varied so the
# compliance + multi-leg-chain optimiser has interesting decisions to make.
# ---------------------------------------------------------------------------
DEPOT_CITY = "Cluj-Napoca"
CARRIER = "Cluj Reefer Logistics"


def truck_fixtures() -> list[dict[str, Any]]:
    return [
        # --- Two pharma 2-8°C vans (the company's most premium asset) -----
        dict(
            plate_number="CJ-101-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="pharma_2_8", last_cargo="pharma",
            has_pharma_logger=True, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-102-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="pharma_2_8", last_cargo="pharma",
            has_pharma_logger=True, remaining_driving_hours=9.0, status="empty",
        ),
        # --- Three chilled vans (dairy, produce, raw meat split) ----------
        dict(
            plate_number="CJ-201-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="chilled", last_cargo="dairy",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-202-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="chilled", last_cargo="produce",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            # last_cargo=raw_meat WITHOUT wash cert -> Analyst will reject
            # non-meat food-grade loads on this van today.
            plate_number="CJ-203-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="chilled", last_cargo="raw_meat",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        # --- Two multi-temp vans (most flexible, most expensive to run) ---
        dict(
            # raw_meat with valid ANSVSA wash → dairy/produce unblocked.
            plate_number="CJ-301-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="multi_temp", last_cargo="raw_meat",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-302-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="multi_temp", last_cargo="clean",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        # --- Two frozen vans (long routes to / from Bucharest, ports) -----
        dict(
            plate_number="CJ-401-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="frozen", last_cargo="frozen",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-402-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="frozen", last_cargo="frozen",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        # --- One ambient/chemicals van (intentionally compliance-blocked) ---
        dict(
            # last_cargo=chemicals + ambient-only cap → HACCP locks out all
            # food-grade work today, leaving only chemicals→chemicals.
            plate_number="CJ-901-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="ambient", last_cargo="chemicals",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        # --- Fleet expansion: 5 additional vans -------------------------
        # The carrier grows; thesis-grade dataset wants fleet at the upper
        # end of the user's "10-15 vans" target. Profiles deliberately
        # varied so the optimiser still has interesting decisions to make
        # (extra pharma capacity, extra chilled with no recent meat history,
        # extra multi_temp / frozen, plus a "clean" ambient van that can
        # actually take food-grade ambient_dry loads — the existing CJ-901
        # is locked out by chemicals quarantine).
        dict(
            plate_number="CJ-103-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="pharma_2_8", last_cargo="pharma",
            has_pharma_logger=True, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-204-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="chilled", last_cargo="clean",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-303-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="multi_temp", last_cargo="dairy",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-403-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="frozen", last_cargo="clean",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
        ),
        dict(
            plate_number="CJ-902-CRL", carrier_name=CARRIER,
            current_city=DEPOT_CITY, home_base_city=DEPOT_CITY,
            temp_capability="ambient", last_cargo="clean",
            has_pharma_logger=False, remaining_driving_hours=9.0, status="empty",
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
# 15 spot-market broker loads — anonymised shippers, ~10–20% lower prices
# than direct customer rates, broader geography. These are what the fleet
# optimiser scoops up to fill empty backhauls when the customer book has
# no matching trip.
# ---------------------------------------------------------------------------
def broker_load_fixtures() -> list[dict[str, Any]]:
    base = TOMORROW_06

    def window(hours_offset: int, window_hours: int = 8) -> tuple[datetime, datetime]:
        start = base + timedelta(hours=hours_offset)
        return start, start + timedelta(hours=window_hours)

    return [
        # B1. Ambient_dry Bucuresti -> Cluj-Napoca (return-leg friendly)
        dict(
            shipper_name="Spot Freight #B-001",
            cargo_type="ambient_dry", cargo_description="Carton goods palletised",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="chemicals",
            pickup_city="Bucuresti", delivery_city="Cluj-Napoca",
            window=window(4, 12), weight_kg=8000, price_eur=380,
        ),
        # B2. Frozen_veg Galati -> Bucuresti (long-distance backhaul)
        dict(
            shipper_name="Spot Freight #B-002",
            cargo_type="frozen_vegetables", cargo_description="IQF mix vegetables",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Galati", delivery_city="Bucuresti",
            window=window(5, 10), weight_kg=11500, price_eur=580,
        ),
        # B3. Pharma Bucuresti -> Cluj-Napoca (spot rate, ~10% under contract)
        dict(
            shipper_name="Spot Freight #B-003",
            cargo_type="pharma", cargo_description="OTC pharma overnight",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Bucuresti", delivery_city="Cluj-Napoca",
            window=window(3, 6), weight_kg=3800, price_eur=1450,
        ),
        # B4. Raw_meat Pitesti -> Bucuresti (small, fills a chilled return)
        dict(
            shipper_name="Spot Freight #B-004",
            cargo_type="raw_meat", cargo_description="Carcase porc spot",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Pitesti", delivery_city="Bucuresti",
            window=window(6, 6), weight_kg=6200, price_eur=320,
        ),
        # B5. Dairy Brasov -> Cluj-Napoca (long chilled trip)
        dict(
            shipper_name="Spot Freight #B-005",
            cargo_type="dairy", cargo_description="Lapte UHT pallets",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Brasov", delivery_city="Cluj-Napoca",
            window=window(5, 8), weight_kg=7500, price_eur=560,
        ),
        # B6. Produce Constanta -> Bucuresti (port-region spot)
        dict(
            shipper_name="Spot Freight #B-006",
            cargo_type="produce", cargo_description="Citrice import port",
            temp_min_celsius=4.0, temp_max_celsius=10.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Constanta", delivery_city="Bucuresti",
            window=window(4, 10), weight_kg=8500, price_eur=420,
        ),
        # B7. Ambient_dry Suceava -> Bucuresti
        dict(
            shipper_name="Spot Freight #B-007",
            cargo_type="ambient_dry", cargo_description="Furniture flat-pack",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Suceava", delivery_city="Bucuresti",
            window=window(7, 10), weight_kg=14000, price_eur=640,
        ),
        # B8. Frozen_fish Galati -> Cluj-Napoca (cross-country frozen)
        dict(
            shipper_name="Spot Freight #B-008",
            cargo_type="frozen_fish", cargo_description="Hering congelat",
            temp_min_celsius=-22.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Galati", delivery_city="Cluj-Napoca",
            window=window(8, 10), weight_kg=9500, price_eur=860,
        ),
        # B9. Chemicals Constanta -> Craiova (industrial spot)
        dict(
            shipper_name="Spot Freight #B-009",
            cargo_type="chemicals", cargo_description="Acid clorhidric tehnic",
            temp_min_celsius=5.0, temp_max_celsius=30.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Constanta", delivery_city="Craiova",
            window=window(6, 12), weight_kg=10000, price_eur=540,
        ),
        # B10. Raw_poultry Brasov -> Bucuresti
        dict(
            shipper_name="Spot Freight #B-010",
            cargo_type="raw_poultry", cargo_description="Pui taiati spot",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Brasov", delivery_city="Bucuresti",
            window=window(5, 7), weight_kg=7000, price_eur=400,
        ),
        # B11. Produce Iasi -> Cluj-Napoca (long chilled spot)
        dict(
            shipper_name="Spot Freight #B-011",
            cargo_type="produce", cargo_description="Cartofi sortati",
            temp_min_celsius=4.0, temp_max_celsius=12.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Iasi", delivery_city="Cluj-Napoca",
            window=window(6, 10), weight_kg=9000, price_eur=560,
        ),
        # B12. Frozen_veg Bacau -> Bucuresti
        dict(
            shipper_name="Spot Freight #B-012",
            cargo_type="frozen_vegetables", cargo_description="Spanac IQF",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Bacau", delivery_city="Bucuresti",
            window=window(5, 9), weight_kg=11000, price_eur=480,
        ),
        # B13. Ambient_dry Oradea -> Constanta (cross-country spot)
        dict(
            shipper_name="Spot Freight #B-013",
            cargo_type="ambient_dry", cargo_description="Recyclables baled",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Oradea", delivery_city="Constanta",
            window=window(4, 14), weight_kg=16000, price_eur=860,
        ),
        # B14. Dairy Suceava -> Iasi (short chilled spot)
        dict(
            shipper_name="Spot Freight #B-014",
            cargo_type="dairy", cargo_description="Branzeturi de stana",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Suceava", delivery_city="Iasi",
            window=window(7, 7), weight_kg=5500, price_eur=290,
        ),
        # B15. Pharma small Cluj-Napoca -> Brasov (high-margin pharma backhaul)
        dict(
            shipper_name="Spot Freight #B-015",
            cargo_type="pharma", cargo_description="Vaccin spot urgent",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Cluj-Napoca", delivery_city="Brasov",
            window=window(4, 4), weight_kg=1800, price_eur=820,
        ),
        # ---- Expansion pack B16-B40 ----
        # 25 more broker loads to give the bigger fleet (15 vans) more
        # matching surface. Heavier emphasis on Cluj-region routes
        # (≤ ~250 km radius) so the depot model has profitable round
        # trips, plus a few cross-country pairs to stress the chain
        # pre-filter and the EU 561/2006 hours-feasibility gate.
        # Prices scaled by route distance and cargo type so the
        # optimiser still has a clear margin ranking.
        # B16. Pharma Cluj -> Sibiu (short premium backhaul)
        dict(
            shipper_name="Spot Freight #B-016",
            cargo_type="pharma", cargo_description="Reactivi laborator",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Cluj-Napoca", delivery_city="Sibiu",
            window=window(3, 5), weight_kg=2200, price_eur=620,
        ),
        # B17. Dairy Sibiu -> Cluj (perfect Cluj backhaul)
        dict(
            shipper_name="Spot Freight #B-017",
            cargo_type="dairy", cargo_description="Iaurt artizanal",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Sibiu", delivery_city="Cluj-Napoca",
            window=window(6, 8), weight_kg=4500, price_eur=380,
        ),
        # B18. Produce Oradea -> Cluj (short return)
        dict(
            shipper_name="Spot Freight #B-018",
            cargo_type="produce", cargo_description="Mere ardelenesti",
            temp_min_celsius=4.0, temp_max_celsius=10.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Oradea", delivery_city="Cluj-Napoca",
            window=window(5, 8), weight_kg=6000, price_eur=320,
        ),
        # B19. Frozen veg Cluj -> Sibiu (chain seed for frozen vans)
        dict(
            shipper_name="Spot Freight #B-019",
            cargo_type="frozen_vegetables", cargo_description="Mazare congelata",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Cluj-Napoca", delivery_city="Sibiu",
            window=window(4, 6), weight_kg=8500, price_eur=440,
        ),
        # B20. Frozen veg Sibiu -> Cluj (return chain)
        dict(
            shipper_name="Spot Freight #B-020",
            cargo_type="frozen_vegetables", cargo_description="Spanac IQF",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Sibiu", delivery_city="Cluj-Napoca",
            window=window(7, 6), weight_kg=7800, price_eur=410,
        ),
        # B21. Raw meat Cluj -> Brasov
        dict(
            shipper_name="Spot Freight #B-021",
            cargo_type="raw_meat", cargo_description="Carcase porc spot",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Brasov",
            window=window(5, 6), weight_kg=10000, price_eur=520,
        ),
        # B22. Ambient_dry Cluj -> Oradea (gives ambient van profitable trip)
        dict(
            shipper_name="Spot Freight #B-022",
            cargo_type="ambient_dry", cargo_description="Carton retail",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Oradea",
            window=window(4, 10), weight_kg=12000, price_eur=380,
        ),
        # B23. Ambient_dry Oradea -> Cluj (chain home for ambient)
        dict(
            shipper_name="Spot Freight #B-023",
            cargo_type="ambient_dry", cargo_description="Apa minerala palet",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Oradea", delivery_city="Cluj-Napoca",
            window=window(8, 8), weight_kg=14000, price_eur=350,
        ),
        # B24. Dairy Cluj -> Sibiu (short chilled run)
        dict(
            shipper_name="Spot Freight #B-024",
            cargo_type="dairy", cargo_description="Smantana fermentata",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Sibiu",
            window=window(5, 6), weight_kg=5500, price_eur=410,
        ),
        # B25. Produce Brasov -> Cluj (return)
        dict(
            shipper_name="Spot Freight #B-025",
            cargo_type="produce", cargo_description="Cartofi sortati",
            temp_min_celsius=4.0, temp_max_celsius=12.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Brasov", delivery_city="Cluj-Napoca",
            window=window(7, 8), weight_kg=8500, price_eur=460,
        ),
        # B26. Pharma Brasov -> Cluj (premium chain leg back)
        dict(
            shipper_name="Spot Freight #B-026",
            cargo_type="pharma", cargo_description="Insulina rece",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Brasov", delivery_city="Cluj-Napoca",
            window=window(5, 5), weight_kg=2400, price_eur=920,
        ),
        # B27. Frozen fish Constanta -> Cluj (long-haul; tests hours feasibility)
        dict(
            shipper_name="Spot Freight #B-027",
            cargo_type="frozen_fish", cargo_description="Pescuit oceanic",
            temp_min_celsius=-22.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Constanta", delivery_city="Cluj-Napoca",
            window=window(3, 12), weight_kg=10500, price_eur=1080,
        ),
        # B28. Raw poultry Cluj -> Sibiu
        dict(
            shipper_name="Spot Freight #B-028",
            cargo_type="raw_poultry", cargo_description="Pui dezosat",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Sibiu",
            window=window(4, 5), weight_kg=6000, price_eur=350,
        ),
        # B29. Dairy Cluj -> Pitesti (medium chilled run)
        dict(
            shipper_name="Spot Freight #B-029",
            cargo_type="dairy", cargo_description="Branzeturi maturate",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Pitesti",
            window=window(5, 8), weight_kg=7500, price_eur=540,
        ),
        # B30. Produce Pitesti -> Cluj (chain return)
        dict(
            shipper_name="Spot Freight #B-030",
            cargo_type="produce", cargo_description="Legume mixte",
            temp_min_celsius=4.0, temp_max_celsius=10.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Pitesti", delivery_city="Cluj-Napoca",
            window=window(8, 8), weight_kg=8000, price_eur=520,
        ),
        # B31. Frozen veg Bucuresti -> Cluj (long-haul backhaul)
        dict(
            shipper_name="Spot Freight #B-031",
            cargo_type="frozen_vegetables", cargo_description="IQF mixt",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Bucuresti", delivery_city="Cluj-Napoca",
            window=window(4, 10), weight_kg=14000, price_eur=780,
        ),
        # B32. Ambient_dry Cluj -> Brasov
        dict(
            shipper_name="Spot Freight #B-032",
            cargo_type="ambient_dry", cargo_description="Mobilier flat-pack",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Cluj-Napoca", delivery_city="Brasov",
            window=window(5, 9), weight_kg=11000, price_eur=420,
        ),
        # B33. Raw meat Sibiu -> Cluj (chain back for chilled meat van)
        dict(
            shipper_name="Spot Freight #B-033",
            cargo_type="raw_meat", cargo_description="Carcase vita",
            temp_min_celsius=0.0, temp_max_celsius=4.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Sibiu", delivery_city="Cluj-Napoca",
            window=window(8, 6), weight_kg=9000, price_eur=440,
        ),
        # B34. Chemicals Cluj -> Oradea (industrial spot, only for chemicals vans)
        dict(
            shipper_name="Spot Freight #B-034",
            cargo_type="chemicals", cargo_description="Detergent industrial",
            temp_min_celsius=5.0, temp_max_celsius=30.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Cluj-Napoca", delivery_city="Oradea",
            window=window(6, 10), weight_kg=12000, price_eur=380,
        ),
        # B35. Frozen fish Galati -> Cluj (very long, hours-infeasible test)
        dict(
            shipper_name="Spot Freight #B-035",
            cargo_type="frozen_fish", cargo_description="Macrou congelat",
            temp_min_celsius=-22.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Galati", delivery_city="Cluj-Napoca",
            window=window(2, 14), weight_kg=11000, price_eur=1180,
        ),
        # B36. Pharma Sibiu -> Cluj (short premium return)
        dict(
            shipper_name="Spot Freight #B-036",
            cargo_type="pharma", cargo_description="Vaccin urgent",
            temp_min_celsius=2.0, temp_max_celsius=8.0,
            requires_pharma_logger=True,
            forbidden_prior_cargo="chemicals,raw_meat,raw_poultry",
            pickup_city="Sibiu", delivery_city="Cluj-Napoca",
            window=window(6, 5), weight_kg=2000, price_eur=560,
        ),
        # B37. Dairy Brasov -> Sibiu (transversal route, not Cluj)
        dict(
            shipper_name="Spot Freight #B-037",
            cargo_type="dairy", cargo_description="Lapte fresh",
            temp_min_celsius=2.0, temp_max_celsius=7.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Brasov", delivery_city="Sibiu",
            window=window(6, 8), weight_kg=6500, price_eur=320,
        ),
        # B38. Frozen veg Cluj -> Brasov
        dict(
            shipper_name="Spot Freight #B-038",
            cargo_type="frozen_vegetables", cargo_description="Fasole congelata",
            temp_min_celsius=-25.0, temp_max_celsius=-18.0,
            requires_pharma_logger=False, forbidden_prior_cargo=None,
            pickup_city="Cluj-Napoca", delivery_city="Brasov",
            window=window(4, 8), weight_kg=10000, price_eur=460,
        ),
        # B39. Produce Constanta -> Cluj (long, chain-friendly)
        dict(
            shipper_name="Spot Freight #B-039",
            cargo_type="produce", cargo_description="Citrice import",
            temp_min_celsius=4.0, temp_max_celsius=10.0,
            requires_pharma_logger=False,
            forbidden_prior_cargo="raw_meat,raw_poultry,chemicals",
            pickup_city="Constanta", delivery_city="Cluj-Napoca",
            window=window(2, 12), weight_kg=9500, price_eur=920,
        ),
        # B40. Ambient_dry Sibiu -> Cluj (short, ambient van's bread-and-butter)
        dict(
            shipper_name="Spot Freight #B-040",
            cargo_type="ambient_dry", cargo_description="Recyclables baled",
            temp_min_celsius=5.0, temp_max_celsius=25.0,
            requires_pharma_logger=False, forbidden_prior_cargo="chemicals",
            pickup_city="Sibiu", delivery_city="Cluj-Napoca",
            window=window(7, 8), weight_kg=13500, price_eur=290,
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
            # CJ-301 was officially sanitised at the Cluj depot wash bay
            # last evening → Analyst can clear it for dairy/produce loads
            # via the ANSVSA wash override.
            plate_number="CJ-301-CRL",
            certificate_number=f"ANSVSA-CJ-{NOW:%Y-%m-%d}-0142",
            issued_at=NOW - timedelta(hours=18),
            valid_until=NOW + timedelta(days=30),  # stays valid across re-runs
            wash_type="ansvsa_official",
            prior_cargo="raw_meat",
            issuing_facility="Cluj Depot Wash Bay — autorizatie ANSVSA CJ-007",
            location_city="Cluj-Napoca",
        ),
        # CJ-901 (ambient van, last_cargo=chemicals) had a deep wash on the
        # return run yesterday but ambient-only so its food-grade reuse is
        # still off-limits per HACCP — kept as a partial / flavour cert.
        dict(
            plate_number="CJ-901-CRL",
            certificate_number=f"WASH-CJ-{NOW:%Y-%m-%d}-0007",
            issued_at=NOW - timedelta(hours=10),
            valid_until=NOW + timedelta(days=30),
            wash_type="deep",
            prior_cargo="chemicals",
            issuing_facility="Cluj Depot Wash Bay",
            location_city="Cluj-Napoca",
        ),
    ]


# ---------------------------------------------------------------------------
# Validation -- runs in --dry-run too, so fixtures stay correct over time.
# ---------------------------------------------------------------------------
def _validate(trucks: list[dict], loads: list[dict], washes: list[dict]) -> None:
    plates = {t["plate_number"] for t in trucks}
    if len(plates) != len(trucks):
        raise ValueError("Duplicate truck plates in fixtures")
    if len(trucks) != 15:
        raise ValueError(f"Expected 15 trucks, got {len(trucks)}")
    customer_count = sum(1 for ld in loads if ld.get("source", "customer") == "customer")
    broker_count = sum(1 for ld in loads if ld.get("source") == "broker")
    if customer_count != 20:
        raise ValueError(f"Expected 20 customer loads, got {customer_count}")
    if broker_count != 40:
        raise ValueError(f"Expected 40 broker loads, got {broker_count}")
    if len(loads) != 60:
        raise ValueError(f"Expected 60 loads total, got {len(loads)}")
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
            source=f.get("source", "customer"),
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
    customer_loads = [{**ld, "source": "customer"} for ld in load_fixtures()]
    broker_loads = [{**ld, "source": "broker"} for ld in broker_load_fixtures()]
    loads = customer_loads + broker_loads
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

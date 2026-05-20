"""Admin endpoints — fleet + load CRUD + random generation + reset.

These power the dispatcher console's "Manage data" modal, where the
operator can populate a custom test scenario manually or with the
random button before pressing "Plan today's routes".

Endpoints (all under `/api/admin`):

  Trucks
    GET    /trucks                 list every truck
    POST   /trucks                 create one
    DELETE /trucks/{id}            delete one
    POST   /trucks/random?count=N  add N random trucks
    DELETE /trucks                 delete ALL trucks (use with care)

  Loads
    GET    /loads                  list every load
    POST   /loads                  create one
    DELETE /loads/{id}             delete one
    POST   /loads/random?count=N   add N random loads
    DELETE /loads                  delete ALL loads

  Workspace
    POST   /reset                  truncate trucks + loads + wash_certs
    POST   /seed                   re-run the canonical 25-van/100-load seed

Cache invalidation: any write here clears the verdict cache so the next
`/api/route/plan` re-evaluates against the new data.

Auth: NONE in v1 — this is a local-only dispatcher tool. Don't expose
to the public internet without adding auth in front.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from geoalchemy2.elements import WKTElement
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.agents import verdict_cache
from app.core.database import SessionLocal
from app.data.romania_cities import ROMANIA_CITIES, wkt_point
from app.models import LoadRequest, Truck, WashCertificate
from app.services.random_fixtures import (
    CARGO_TYPES, TRUCK_CAPABILITIES, TRUCK_LAST_CARGOES,
    random_load_payload, random_truck_payload,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class TruckIn(BaseModel):
    plate_number: str = Field(min_length=3, max_length=16)
    carrier_name: str = Field(default="Cluj Reefer Logistics", max_length=128)
    temp_capability: str
    last_cargo: str
    has_pharma_logger: bool = False
    remaining_driving_hours: float = 9.0
    status: str = "empty"
    home_base_city: str = "Cluj-Napoca"
    current_city: str = "Cluj-Napoca"


class LoadIn(BaseModel):
    shipper_name: str = Field(default="Manual entry", max_length=128)
    cargo_type: str
    cargo_description: str = Field(default="", max_length=256)
    temp_min_celsius: float
    temp_max_celsius: float
    requires_pharma_logger: bool = False
    forbidden_prior_cargo: str | None = None
    pickup_city: str
    delivery_city: str
    # ISO strings; we coerce at write
    pickup_window_start: datetime
    pickup_window_end: datetime
    weight_kg: float = Field(gt=0, le=40_000)
    price_eur: float = Field(ge=0, le=100_000)
    source: str = "customer"   # "customer" | "broker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_db():
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not configured")


def _invalidate_caches() -> None:
    """Clear the verdict cache so the next /plan re-evaluates against
    the new data. The LLM cache stays warm — its entries are keyed by
    prompt content, not by truck/load IDs, so existing entries remain
    valid; only verdicts (which embed truck features) need refresh.

    Why we clear instead of selectively invalidate: cheaper. The next
    plan run re-populates it within seconds (verdict cache writes are
    incremental).
    """
    verdict_cache.clear()


def _validate_enum(value: str, allowed: tuple, *, field: str) -> None:
    if value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be one of {sorted(allowed)}; got {value!r}",
        )


def _validate_city(city: str, *, field: str) -> None:
    if city not in ROMANIA_CITIES:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be a known Romanian city. "
                   f"Allowed: {sorted(ROMANIA_CITIES.keys())}. Got {city!r}.",
        )


def _pt(city: str):
    return WKTElement(wkt_point(city), srid=4326)


# ---------------------------------------------------------------------------
# Truck endpoints
# ---------------------------------------------------------------------------

@router.get("/trucks", summary="List every truck")
def list_trucks() -> list[dict]:
    _require_db()
    with SessionLocal() as s:
        rows = s.execute(text("""
            SELECT id, plate_number, carrier_name, temp_capability, last_cargo,
                   has_pharma_logger, remaining_driving_hours, status,
                   current_city, home_base_city,
                   ST_Y(current_location::geometry) AS lat,
                   ST_X(current_location::geometry) AS lon
              FROM trucks
             ORDER BY id
        """)).all()
    return [dict(r._mapping) for r in rows]


@router.post("/trucks", summary="Create a truck", status_code=201)
def create_truck(body: TruckIn) -> dict:
    _require_db()
    _validate_enum(body.temp_capability, TRUCK_CAPABILITIES, field="temp_capability")
    _validate_enum(body.last_cargo, TRUCK_LAST_CARGOES, field="last_cargo")
    _validate_city(body.current_city, field="current_city")
    _validate_city(body.home_base_city, field="home_base_city")

    with SessionLocal() as s:
        truck = Truck(
            plate_number=body.plate_number,
            carrier_name=body.carrier_name,
            temp_capability=body.temp_capability,
            last_cargo=body.last_cargo,
            has_pharma_logger=body.has_pharma_logger,
            remaining_driving_hours=body.remaining_driving_hours,
            status=body.status,
            current_location=_pt(body.current_city),
            current_city=body.current_city,
            home_base_city=body.home_base_city,
        )
        s.add(truck)
        try:
            s.commit()
        except Exception as exc:
            s.rollback()
            raise HTTPException(status_code=409, detail=f"DB error: {exc}") from exc
        s.refresh(truck)
        out = {"id": truck.id, "plate_number": truck.plate_number,
               "temp_capability": truck.temp_capability,
               "last_cargo": truck.last_cargo,
               "has_pharma_logger": truck.has_pharma_logger}
    _invalidate_caches()
    return out


@router.delete("/trucks/{truck_id}", summary="Delete one truck")
def delete_truck(truck_id: int) -> dict:
    _require_db()
    with SessionLocal() as s:
        # Delete wash certificates first to avoid FK violation
        s.execute(text("DELETE FROM wash_certificates WHERE truck_id = :id"),
                  {"id": truck_id})
        result = s.execute(text("DELETE FROM trucks WHERE id = :id"),
                           {"id": truck_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"truck {truck_id} not found")
        s.commit()
    _invalidate_caches()
    return {"deleted": truck_id}


@router.delete("/trucks", summary="Delete ALL trucks (wipes wash certs too)")
def delete_all_trucks() -> dict:
    _require_db()
    with SessionLocal() as s:
        n = s.execute(text("SELECT count(*) FROM trucks")).scalar()
        s.execute(text("TRUNCATE TABLE wash_certificates RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE TABLE trucks RESTART IDENTITY CASCADE"))
        s.commit()
    _invalidate_caches()
    return {"deleted": n}


@router.post("/trucks/random", summary="Add N random trucks")
def create_random_trucks(count: int = Query(1, ge=1, le=50)) -> dict:
    _require_db()
    created = []
    with SessionLocal() as s:
        existing_plates = {
            r[0] for r in s.execute(text("SELECT plate_number FROM trucks")).all()
        }
        for _ in range(count):
            # Avoid plate collisions
            for _attempt in range(20):
                payload = random_truck_payload()
                if payload["plate_number"] not in existing_plates:
                    break
            else:
                raise HTTPException(status_code=500, detail="Could not generate unique plate")
            existing_plates.add(payload["plate_number"])
            truck = Truck(
                plate_number=payload["plate_number"],
                carrier_name=payload["carrier_name"],
                temp_capability=payload["temp_capability"],
                last_cargo=payload["last_cargo"],
                has_pharma_logger=payload["has_pharma_logger"],
                remaining_driving_hours=payload["remaining_driving_hours"],
                status=payload["status"],
                current_location=_pt(payload["current_city"]),
                current_city=payload["current_city"],
                home_base_city=payload["home_base_city"],
            )
            s.add(truck)
            s.flush()
            created.append({"id": truck.id, "plate_number": truck.plate_number,
                            "temp_capability": truck.temp_capability,
                            "last_cargo": truck.last_cargo})
        s.commit()
    _invalidate_caches()
    return {"created": len(created), "trucks": created}


# ---------------------------------------------------------------------------
# Load endpoints
# ---------------------------------------------------------------------------

@router.get("/loads", summary="List every load")
def list_loads() -> list[dict]:
    _require_db()
    with SessionLocal() as s:
        rows = s.execute(text("""
            SELECT id, shipper_name, cargo_type, cargo_description,
                   temp_min_celsius, temp_max_celsius,
                   requires_pharma_logger, forbidden_prior_cargo,
                   pickup_city, delivery_city, weight_kg, price_eur,
                   status, source, pickup_window_start, pickup_window_end,
                   ST_Y(pickup_location::geometry)   AS pickup_lat,
                   ST_X(pickup_location::geometry)   AS pickup_lon,
                   ST_Y(delivery_location::geometry) AS delivery_lat,
                   ST_X(delivery_location::geometry) AS delivery_lon
              FROM load_requests
             ORDER BY id
        """)).all()
    return [dict(r._mapping) for r in rows]


@router.post("/loads", summary="Create a load", status_code=201)
def create_load(body: LoadIn) -> dict:
    _require_db()
    _validate_enum(body.cargo_type, CARGO_TYPES, field="cargo_type")
    _validate_city(body.pickup_city, field="pickup_city")
    _validate_city(body.delivery_city, field="delivery_city")
    if body.pickup_window_end <= body.pickup_window_start:
        raise HTTPException(status_code=400,
                            detail="pickup_window_end must be after pickup_window_start")
    if body.temp_max_celsius < body.temp_min_celsius:
        raise HTTPException(status_code=400,
                            detail="temp_max_celsius must be >= temp_min_celsius")

    with SessionLocal() as s:
        load = LoadRequest(
            shipper_name=body.shipper_name,
            cargo_type=body.cargo_type,
            cargo_description=body.cargo_description or f"Manual {body.cargo_type}",
            temp_min_celsius=body.temp_min_celsius,
            temp_max_celsius=body.temp_max_celsius,
            requires_pharma_logger=body.requires_pharma_logger,
            forbidden_prior_cargo=body.forbidden_prior_cargo,
            pickup_location=_pt(body.pickup_city),
            pickup_city=body.pickup_city,
            delivery_location=_pt(body.delivery_city),
            delivery_city=body.delivery_city,
            pickup_window_start=body.pickup_window_start,
            pickup_window_end=body.pickup_window_end,
            weight_kg=body.weight_kg,
            price_eur=body.price_eur,
            status="available",
            source=body.source,
        )
        s.add(load)
        s.commit()
        s.refresh(load)
        out = {"id": load.id, "shipper_name": load.shipper_name,
               "cargo_type": load.cargo_type,
               "route": f"{load.pickup_city} -> {load.delivery_city}"}
    _invalidate_caches()
    return out


@router.delete("/loads/{load_id}", summary="Delete one load")
def delete_load(load_id: int) -> dict:
    _require_db()
    with SessionLocal() as s:
        result = s.execute(text("DELETE FROM load_requests WHERE id = :id"),
                           {"id": load_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"load {load_id} not found")
        s.commit()
    _invalidate_caches()
    return {"deleted": load_id}


@router.delete("/loads", summary="Delete ALL loads")
def delete_all_loads() -> dict:
    _require_db()
    with SessionLocal() as s:
        n = s.execute(text("SELECT count(*) FROM load_requests")).scalar()
        s.execute(text("TRUNCATE TABLE load_requests RESTART IDENTITY CASCADE"))
        s.commit()
    _invalidate_caches()
    return {"deleted": n}


@router.post("/loads/random", summary="Add N random loads")
def create_random_loads(count: int = Query(1, ge=1, le=100)) -> dict:
    _require_db()
    created = []
    with SessionLocal() as s:
        for _ in range(count):
            payload = random_load_payload()
            load = LoadRequest(
                shipper_name=payload["shipper_name"],
                cargo_type=payload["cargo_type"],
                cargo_description=payload["cargo_description"],
                temp_min_celsius=payload["temp_min_celsius"],
                temp_max_celsius=payload["temp_max_celsius"],
                requires_pharma_logger=payload["requires_pharma_logger"],
                forbidden_prior_cargo=payload["forbidden_prior_cargo"],
                pickup_location=_pt(payload["pickup_city"]),
                pickup_city=payload["pickup_city"],
                delivery_location=_pt(payload["delivery_city"]),
                delivery_city=payload["delivery_city"],
                pickup_window_start=payload["pickup_window_start"],
                pickup_window_end=payload["pickup_window_end"],
                weight_kg=payload["weight_kg"],
                price_eur=payload["price_eur"],
                status=payload["status"],
                source=payload["source"],
            )
            s.add(load)
            s.flush()
            created.append({"id": load.id, "cargo_type": load.cargo_type,
                            "route": f"{load.pickup_city} -> {load.delivery_city}",
                            "price_eur": load.price_eur})
        s.commit()
    _invalidate_caches()
    return {"created": len(created), "loads": created}


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------

@router.post("/reset", summary="Truncate trucks + loads + wash certs (empty workspace)")
def reset_workspace() -> dict:
    _require_db()
    with SessionLocal() as s:
        s.execute(text(
            "TRUNCATE TABLE route_history, wash_certificates, load_requests, trucks "
            "RESTART IDENTITY CASCADE"
        ))
        s.commit()
    _invalidate_caches()
    return {"status": "reset", "trucks": 0, "loads": 0}


@router.post("/seed", summary="Re-run the canonical 25-van/100-load seed")
def reseed_canonical() -> dict:
    _require_db()
    # Lazy import — pulls in fixture data
    from scripts.seed_data import (
        truck_fixtures, load_fixtures, broker_load_fixtures,
        wash_cert_fixtures, _validate,
    )
    trucks = truck_fixtures()
    customer_loads = [{**ld, "source": "customer"} for ld in load_fixtures()]
    broker_loads = [{**ld, "source": "broker"} for ld in broker_load_fixtures()]
    loads = customer_loads + broker_loads
    washes = wash_cert_fixtures()
    _validate(trucks, loads, washes)

    with SessionLocal() as s:
        s.execute(text(
            "TRUNCATE TABLE route_history, wash_certificates, load_requests, trucks "
            "RESTART IDENTITY CASCADE"
        ))
        plate_to_id: dict[str, int] = {}
        for f in trucks:
            t = Truck(
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
            s.add(t); s.flush()
            plate_to_id[t.plate_number] = t.id
        for f in loads:
            win_start, win_end = f["window"]
            s.add(LoadRequest(
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
                pickup_window_start=win_start, pickup_window_end=win_end,
                weight_kg=f["weight_kg"], price_eur=f["price_eur"],
                status="available", source=f.get("source", "customer"),
            ))
        for f in washes:
            s.add(WashCertificate(
                truck_id=plate_to_id[f["plate_number"]],
                certificate_number=f["certificate_number"],
                issued_at=f["issued_at"],
                valid_until=f["valid_until"],
                wash_type=f["wash_type"],
                prior_cargo=f["prior_cargo"],
                issuing_facility=f["issuing_facility"],
                location=_pt(f["location_city"]),
            ))
        s.commit()
    _invalidate_caches()
    return {"status": "seeded", "trucks": len(trucks), "loads": len(loads),
            "washes": len(washes)}


@router.get("/enums", summary="Return all enum sets the frontend forms need")
def list_enums() -> dict:
    return {
        "truck_capabilities": list(TRUCK_CAPABILITIES),
        "truck_last_cargoes": list(TRUCK_LAST_CARGOES),
        "cargo_types": list(CARGO_TYPES),
        "cities": sorted(ROMANIA_CITIES.keys()),
        "load_sources": ["customer", "broker"],
    }


# ---------------------------------------------------------------------------
# 123cargo Frigo dataset — real-world freight imported from the user's
# authenticated session on 123cargo.eu (see scripts/scrape_123cargo.py).
# Endpoints below let the dispatcher console pull a subset of those real
# loads into the workspace for testing.
#
# The mapping (cargo-type heuristic + price derivation + LoadSnapshot
# shape) lives in `app.services.load_123cargo` so the R-series
# experiment scripts can reuse the exact same path the API uses.
# ---------------------------------------------------------------------------

from app.services import load_123cargo as l123c


@router.get("/loads/123cargo/info", summary="How many Frigo loads are in the local dataset")
def info_123cargo() -> dict:
    if not l123c.dataset_exists():
        return {"available": 0, "scraped_at_utc": None, "exists": False}
    data = l123c.load_dataset()
    return {
        "available":       data.get("frigo_count", 0),
        "scraped_at_utc":  data.get("scraped_at_utc"),
        "base_search_date": data.get("base_search_date"),
        "total_scanned":   data.get("total_scanned"),
        "total_available": data.get("total_available"),
        "exists":          True,
    }


@router.post("/loads/123cargo/import", summary="Import N Frigo loads from the scraped dataset")
def import_123cargo(count: int = Query(20, ge=1, le=500),
                    shuffle: bool = Query(True, description="Pick a random subset instead of the first N")) -> dict:
    _require_db()
    try:
        data = l123c.load_dataset()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rows = list(data.get("loads", []))
    if not rows:
        raise HTTPException(status_code=404, detail="123cargo dataset is empty")

    import random as _r
    if shuffle:
        _r.shuffle(rows)
    rows = rows[:count]

    from datetime import timedelta
    from app.services.random_fixtures import _CARGO_DEFAULTS  # type: ignore[attr-defined]
    base_time = datetime.now(timezone.utc).replace(
        hour=8, minute=0, second=0, microsecond=0,
    )

    created = []
    with SessionLocal() as s:
        for r in rows:
            cargo = l123c.guess_cargo_type(r)
            d = _CARGO_DEFAULTS[cargo]
            # 123cargo gives lat/lng; we POINT() them directly (no city table lookup)
            pickup_wkt = WKTElement(f"POINT({r['source_lng']} {r['source_lat']})", srid=4326)
            deliv_wkt = WKTElement(f"POINT({r['destination_lng']} {r['destination_lat']})", srid=4326)
            # Time window: pickup in 2-12h, 8h wide. We deliberately don't use
            # the original 123cargo loading_date because most scraped rows are
            # for "yesterday" relative to current wall-clock, which would make
            # them all expired the moment they hit our DB.
            offset_h = 2 + (abs(hash(r["id"])) % 11)
            win_start = base_time + timedelta(hours=offset_h)
            win_end = win_start + timedelta(hours=8)
            load = LoadRequest(
                shipper_name=f"123cargo {r['id']}",
                cargo_type=cargo,
                cargo_description=f"Real freight from 123cargo.eu — "
                                   f"{r['raw_source']} → {r['raw_destination']}",
                temp_min_celsius=d["temp"][0],
                temp_max_celsius=d["temp"][1],
                requires_pharma_logger=d["logger"],
                forbidden_prior_cargo=d["fpc"],
                pickup_location=pickup_wkt,
                pickup_city=r["source_city"],
                delivery_location=deliv_wkt,
                delivery_city=r["destination_city"],
                pickup_window_start=win_start,
                pickup_window_end=win_end,
                weight_kg=float(r["weight_kg"] or 1000),
                price_eur=l123c.derive_price_eur(r),
                status="available",
                source="broker",
            )
            s.add(load)
            s.flush()
            created.append({"id": load.id, "cargo_type": load.cargo_type,
                            "route": f"{load.pickup_city} → {load.delivery_city}",
                            "weight_kg": load.weight_kg,
                            "price_eur": round(load.price_eur, 0),
                            "123cargo_id": r["id"]})
        s.commit()
    _invalidate_caches()
    return {"created": len(created),
            "source": "123cargo.eu",
            "available_in_dataset": data.get("frigo_count", 0),
            "loads": created}

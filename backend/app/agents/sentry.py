"""Agent 1 — Sentry.

Watches Supabase for empty trucks. When invoked with a specific truck id,
hydrates the full TruckSnapshot (incl. coordinates from PostGIS and any
currently-valid wash certificates) plus the list of available loads.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from app.agents.state import LoadSnapshot, TruckSnapshot, WorkflowState
from app.core.database import SessionLocal


_TRUCK_SQL = text("""
    SELECT id, plate_number, carrier_name, temp_capability, last_cargo,
           has_pharma_logger, remaining_driving_hours, status,
           current_city, home_base_city,
           ST_Y(current_location::geometry) AS lat,
           ST_X(current_location::geometry) AS lon
    FROM trucks
    WHERE id = :truck_id
""")

_WASH_SQL = text("""
    SELECT certificate_number, issued_at, valid_until, wash_type,
           prior_cargo, issuing_facility
    FROM wash_certificates
    WHERE truck_id = :truck_id
    ORDER BY valid_until DESC
""")

_LOADS_SQL = text("""
    SELECT id, shipper_name, cargo_type, cargo_description,
           temp_min_celsius, temp_max_celsius, requires_pharma_logger,
           forbidden_prior_cargo,
           pickup_city, delivery_city,
           ST_Y(pickup_location::geometry)   AS pickup_lat,
           ST_X(pickup_location::geometry)   AS pickup_lon,
           ST_Y(delivery_location::geometry) AS delivery_lat,
           ST_X(delivery_location::geometry) AS delivery_lon,
           pickup_window_start, pickup_window_end,
           weight_kg, price_eur, status
    FROM load_requests
    WHERE status = 'available' AND pickup_window_end >= :now
    ORDER BY id
""")


def _row_to_truck(row, washes: list[dict]) -> TruckSnapshot:
    return TruckSnapshot(
        id=row.id,
        plate_number=row.plate_number,
        carrier_name=row.carrier_name,
        temp_capability=row.temp_capability,
        last_cargo=row.last_cargo,
        has_pharma_logger=row.has_pharma_logger,
        remaining_driving_hours=row.remaining_driving_hours,
        status=row.status,
        current_city=row.current_city,
        home_base_city=row.home_base_city,
        lat=float(row.lat),
        lon=float(row.lon),
        wash_certificates=washes,
    )


def _row_to_load(row) -> LoadSnapshot:
    return LoadSnapshot(
        id=row.id,
        shipper_name=row.shipper_name,
        cargo_type=row.cargo_type,
        cargo_description=row.cargo_description,
        temp_min_celsius=float(row.temp_min_celsius),
        temp_max_celsius=float(row.temp_max_celsius),
        requires_pharma_logger=row.requires_pharma_logger,
        forbidden_prior_cargo=row.forbidden_prior_cargo,
        pickup_city=row.pickup_city,
        delivery_city=row.delivery_city,
        pickup_lat=float(row.pickup_lat),
        pickup_lon=float(row.pickup_lon),
        delivery_lat=float(row.delivery_lat),
        delivery_lon=float(row.delivery_lon),
        pickup_window_start=row.pickup_window_start.isoformat(),
        pickup_window_end=row.pickup_window_end.isoformat(),
        weight_kg=float(row.weight_kg),
        price_eur=float(row.price_eur),
        status=row.status,
    )


def sentry_node(state: WorkflowState) -> dict:
    if SessionLocal is None:
        return {"error": "SUPABASE_DATABASE_URL is not configured"}

    truck_id = state.get("truck_id")
    if not truck_id:
        return {"error": "Sentry requires state['truck_id']"}

    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        row = session.execute(_TRUCK_SQL, {"truck_id": truck_id}).first()
        if row is None:
            return {"error": f"truck id={truck_id} not found"}

        wash_rows = session.execute(_WASH_SQL, {"truck_id": truck_id}).all()
        washes = [{
            "certificate_number": w.certificate_number,
            "issued_at": w.issued_at.isoformat(),
            "valid_until": w.valid_until.isoformat(),
            "wash_type": w.wash_type,
            "prior_cargo": w.prior_cargo,
            "issuing_facility": w.issuing_facility,
            "is_currently_valid": w.issued_at <= now <= w.valid_until,
        } for w in wash_rows]

        load_rows = session.execute(_LOADS_SQL, {"now": now}).all()
        loads = [_row_to_load(r) for r in load_rows]

    truck = _row_to_truck(row, washes)

    sentry_log = {
        "truck_status": truck["status"],
        "available_load_count": len(loads),
        "wash_certificate_count": len(washes),
        "valid_wash_certificate_count": sum(1 for w in washes if w["is_currently_valid"]),
        "monitored_at": now.isoformat(),
    }

    if truck["status"] not in ("empty", "loaded"):
        return {
            "truck": truck, "available_loads": loads, "sentry_log": sentry_log,
            "error": f"truck {truck['plate_number']} status='{truck['status']}' is not actionable",
        }

    return {"truck": truck, "available_loads": loads, "sentry_log": sentry_log}

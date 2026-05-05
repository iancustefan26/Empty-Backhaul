"""GET /api/loads/live — GeoJSON FeatureCollection of all available backhaul loads.

Each Feature's geometry is the pickup point. Delivery coordinates are kept in
properties so the frontend can draw pickup -> delivery polylines on demand.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.database import SessionLocal

router = APIRouter(tags=["loads"])


_LIVE_SQL = text("""
    SELECT id, shipper_name, cargo_type, cargo_description,
           temp_min_celsius, temp_max_celsius, requires_pharma_logger,
           forbidden_prior_cargo,
           pickup_city, delivery_city,
           weight_kg, price_eur, status, source,
           pickup_window_start, pickup_window_end,
           ST_AsGeoJSON(pickup_location::geometry)   AS pickup_geojson,
           ST_X(delivery_location::geometry)         AS delivery_lon,
           ST_Y(delivery_location::geometry)         AS delivery_lat
    FROM load_requests
    WHERE status = 'available'
    ORDER BY id
""")


@router.get("/loads/live", summary="GeoJSON FeatureCollection of all available loads")
def loads_live() -> dict:
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    with SessionLocal() as session:
        rows = session.execute(_LIVE_SQL).all()

    features = []
    for r in rows:
        geom = json.loads(r.pickup_geojson) if r.pickup_geojson else None
        features.append({
            "type": "Feature",
            "id": r.id,
            "geometry": geom,
            "properties": {
                "shipper_name": r.shipper_name,
                "cargo_type": r.cargo_type,
                "cargo_description": r.cargo_description,
                "temp_min_celsius": r.temp_min_celsius,
                "temp_max_celsius": r.temp_max_celsius,
                "requires_pharma_logger": r.requires_pharma_logger,
                "forbidden_prior_cargo": r.forbidden_prior_cargo,
                "pickup_city": r.pickup_city,
                "delivery_city": r.delivery_city,
                "delivery_lat": float(r.delivery_lat),
                "delivery_lon": float(r.delivery_lon),
                "weight_kg": r.weight_kg,
                "price_eur": r.price_eur,
                "status": r.status,
                "source": r.source,
                "pickup_window_start": r.pickup_window_start.isoformat(),
                "pickup_window_end": r.pickup_window_end.isoformat(),
            },
        })

    return {
        "type": "FeatureCollection",
        "feature_count": len(features),
        "features": features,
    }

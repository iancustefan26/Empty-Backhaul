"""GET /api/trucks/live — GeoJSON FeatureCollection of all trucks."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.database import SessionLocal

router = APIRouter(tags=["Camioane"])


_LIVE_SQL = text("""
    SELECT id, plate_number, carrier_name, temp_capability, last_cargo,
           has_pharma_logger, remaining_driving_hours, status,
           current_city, home_base_city,
           ST_AsGeoJSON(current_location::geometry) AS geojson
    FROM trucks
    ORDER BY id
""")


@router.get("/trucks/live", summary="GeoJSON FeatureCollection cu toate camioanele")
def trucks_live() -> dict:
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    with SessionLocal() as session:
        rows = session.execute(_LIVE_SQL).all()

    features = []
    for r in rows:
        geom = json.loads(r.geojson) if r.geojson else None
        features.append({
            "type": "Feature",
            "id": r.id,
            "geometry": geom,
            "properties": {
                "plate_number": r.plate_number,
                "carrier_name": r.carrier_name,
                "temp_capability": r.temp_capability,
                "last_cargo": r.last_cargo,
                "has_pharma_logger": r.has_pharma_logger,
                "remaining_driving_hours": r.remaining_driving_hours,
                "status": r.status,
                "current_city": r.current_city,
                "home_base_city": r.home_base_city,
            },
        })

    return {
        "type": "FeatureCollection",
        "feature_count": len(features),
        "features": features,
    }

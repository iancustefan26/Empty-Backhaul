"""Coordinates of Romanian cities used by trucks, loads, and routing demos.

Lat/lon are WGS84 (EPSG:4326). Centroid-of-city is good enough for a prototype.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    county: str


ROMANIA_CITIES: dict[str, City] = {
    "Bucuresti":   City("Bucuresti",   44.4268, 26.1025, "Bucuresti"),
    "Oradea":      City("Oradea",      47.0465, 21.9189, "Bihor"),
    "Cluj-Napoca": City("Cluj-Napoca", 46.7712, 23.6236, "Cluj"),
    "Timisoara":   City("Timisoara",   45.7489, 21.2087, "Timis"),
    "Iasi":        City("Iasi",        47.1585, 27.6014, "Iasi"),
    "Constanta":   City("Constanta",   44.1598, 28.6348, "Constanta"),
    "Sibiu":       City("Sibiu",       45.7983, 24.1256, "Sibiu"),
    "Brasov":      City("Brasov",      45.6427, 25.5887, "Brasov"),
    "Craiova":     City("Craiova",     44.3302, 23.7949, "Dolj"),
    "Ploiesti":    City("Ploiesti",    44.9469, 26.0297, "Prahova"),
    "Galati":      City("Galati",      45.4353, 28.0080, "Galati"),
    "Pitesti":     City("Pitesti",     44.8606, 24.8678, "Arges"),
    "Arad":        City("Arad",        46.1866, 21.3123, "Arad"),
    "Bacau":       City("Bacau",       46.5670, 26.9146, "Bacau"),
    "Suceava":     City("Suceava",     47.6635, 26.2732, "Suceava"),
}


def city(name: str) -> City:
    if name not in ROMANIA_CITIES:
        raise KeyError(f"Unknown Romanian city in fixtures: {name!r}")
    return ROMANIA_CITIES[name]


def wkt_point(name: str) -> str:
    """Return a WKT POINT string for the given city (lon lat ordering)."""
    c = city(name)
    return f"POINT({c.lon} {c.lat})"

"""Targeted tests for the depot-based daily route planner.

Per user direction we keep the test set small — just enough to pin the
structural guarantees the rest of the system (and the experiments PR4)
depends on. End-to-end correctness is validated by the experiments.
"""
from __future__ import annotations

from app.agents.route_planner import plan_fleet_routes
from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot

# Cluj-Napoca depot
CLUJ_LAT, CLUJ_LON = 46.7712, 23.6236
BRASOV_LAT, BRASOV_LON = 45.6427, 25.5887
SIBIU_LAT, SIBIU_LON = 45.7983, 24.1256


def make_van(id_: int, plate: str, **overrides) -> TruckSnapshot:
    base = dict(
        id=id_, plate_number=plate, carrier_name="Test",
        temp_capability="multi_temp", last_cargo="clean",
        has_pharma_logger=True, remaining_driving_hours=9.0,
        status="empty", current_city="Cluj-Napoca", home_base_city="Cluj-Napoca",
        lat=CLUJ_LAT, lon=CLUJ_LON, wash_certificates=[],
    )
    base.update(overrides)
    return TruckSnapshot(**base)


def make_load(id_: int, *, source="customer", price=600.0,
              pickup_lat=CLUJ_LAT, pickup_lon=CLUJ_LON,
              delivery_lat=BRASOV_LAT, delivery_lon=BRASOV_LON,
              pickup_city="Cluj-Napoca", delivery_city="Brasov",
              **overrides) -> LoadSnapshot:
    base = dict(
        id=id_, shipper_name=f"Shipper {id_}",
        cargo_type="dairy", cargo_description="test",
        temp_min_celsius=2.0, temp_max_celsius=6.0,
        requires_pharma_logger=False, forbidden_prior_cargo=None,
        pickup_city=pickup_city, delivery_city=delivery_city,
        pickup_lat=pickup_lat, pickup_lon=pickup_lon,
        delivery_lat=delivery_lat, delivery_lon=delivery_lon,
        pickup_window_start="2026-05-06T08:00",
        pickup_window_end="2026-05-06T18:00",
        weight_kg=8000.0, price_eur=price, status="available",
        source=source,
    )
    base.update(overrides)
    return LoadSnapshot(**base)


def compliant(van_id: int, load_id: int) -> ComplianceVerdict:
    return ComplianceVerdict(
        load_id=load_id, is_compliant=True, confidence=0.95,
        blockers=[], warnings=[], reasoning="ok",
        cited_rule_ids=[], cited_excerpts=[], sanity_overrides=[],
    )


def all_compliant(vans, loads):
    return {(v["id"], l["id"]): compliant(v["id"], l["id"]) for v in vans for l in loads}


# ---------------------------------------------------------------------------

def test_round_trip_includes_return_leg():
    """A SINGLE plan has 3 legs (depot → pickup → delivery → depot) and the
    return leg must be present (depot model)."""
    van = make_van(1, "CJ-001-CRL")
    load = make_load(10, price=900.0)
    result = plan_fleet_routes([van], [load], all_compliant([van], [load]), top_k=1)
    plan = result["alternatives"][0]
    single = next(p for p in plan["plans"] if p["kind"] == "SINGLE")
    assert len(single["legs"]) == 3
    # The last leg returns to the van's current_city (depot).
    assert single["legs"][-1]["to_city"] == "Cluj-Napoca"
    # Both empty legs must be present in the totals.
    assert single["empty_km"] > 0


def test_chain_with_perfect_backhaul_has_zero_inter_leg_deadhead():
    """A van that takes Cluj→Brasov + Brasov→Cluj should chain perfectly,
    yielding 0 km between the two loaded legs. Total trip = 2 × loaded km."""
    van = make_van(1, "CJ-001-CRL")
    load_out = make_load(10, price=400.0,
                         pickup_lat=CLUJ_LAT, pickup_lon=CLUJ_LON,
                         delivery_lat=BRASOV_LAT, delivery_lon=BRASOV_LON,
                         pickup_city="Cluj-Napoca", delivery_city="Brasov")
    load_back = make_load(11, price=400.0,
                          pickup_lat=BRASOV_LAT, pickup_lon=BRASOV_LON,
                          delivery_lat=CLUJ_LAT, delivery_lon=CLUJ_LON,
                          pickup_city="Brasov", delivery_city="Cluj-Napoca")
    result = plan_fleet_routes(
        [van], [load_out, load_back],
        all_compliant([van], [load_out, load_back]), top_k=1,
    )
    plan = result["alternatives"][0]
    chain = next(p for p in plan["plans"] if p["kind"] == "CHAIN")
    assert chain["load_ids"] == [10, 11]
    # Chain has 5 legs and the empty km should be 0 (perfect Cluj-Brasov-Cluj).
    assert len(chain["legs"]) == 5
    assert chain["empty_km"] == 0.0


def test_van_returns_to_depot_eod():
    """Every non-IDLE plan must end with the van back at its depot city."""
    van = make_van(1, "CJ-001-CRL")
    loads = [
        make_load(10, price=900.0),
        make_load(11, price=200.0,
                  pickup_lat=BRASOV_LAT, pickup_lon=BRASOV_LON,
                  delivery_lat=SIBIU_LAT, delivery_lon=SIBIU_LON,
                  pickup_city="Brasov", delivery_city="Sibiu"),
    ]
    result = plan_fleet_routes([van], loads, all_compliant([van], loads), top_k=1)
    for plan in result["alternatives"]:
        for p in plan["plans"]:
            if p["kind"] == "IDLE":
                continue
            assert p["legs"][-1]["to_city"] == van["current_city"]


def test_load_assigned_at_most_once_across_fleet():
    """If two vans are both compliant for the same load, only one can take
    it across the chosen plan."""
    vans = [make_van(1, "CJ-001-CRL"), make_van(2, "CJ-002-CRL")]
    load = make_load(10, price=900.0)
    result = plan_fleet_routes(vans, [load], all_compliant(vans, [load]), top_k=1)
    plan = result["alternatives"][0]
    assignments = [p for p in plan["plans"] if p["kind"] != "IDLE"]
    assert len(assignments) == 1


def test_no_profitable_round_trip_returns_idle():
    """A round-trip whose cost exceeds the load price must NOT be selected;
    the van stays idle."""
    van = make_van(1, "CJ-001-CRL")
    # 0.85 €/km × ~1000 km round trip = €850 cost; load only pays €100.
    load = make_load(10, price=100.0,
                     pickup_lat=44.4268, pickup_lon=26.1025,    # Bucuresti
                     delivery_lat=44.1598, delivery_lon=28.6348, # Constanta
                     pickup_city="Bucuresti", delivery_city="Constanta")
    result = plan_fleet_routes([van], [load], all_compliant([van], [load]), top_k=1)
    plan = result["alternatives"][0]
    assert plan["plans"][0]["kind"] == "IDLE"
    assert plan["total_fleet_margin_eur"] == 0.0


def test_chain_inter_leg_deadhead_capped():
    """Two loads whose between-cities distance > MAX_INTER_LEG_DEADHEAD_KM
    must NOT form a chain. Cluj → Brasov → Constanta would be ~500 km
    deadhead between legs — over the cap."""
    van = make_van(1, "CJ-001-CRL")
    load1 = make_load(10, price=400.0,
                      pickup_lat=CLUJ_LAT, pickup_lon=CLUJ_LON,
                      delivery_lat=BRASOV_LAT, delivery_lon=BRASOV_LON,
                      pickup_city="Cluj-Napoca", delivery_city="Brasov")
    load2 = make_load(11, price=400.0,
                      pickup_lat=44.1598, pickup_lon=28.6348,    # Constanta
                      delivery_lat=CLUJ_LAT, delivery_lon=CLUJ_LON,
                      pickup_city="Constanta", delivery_city="Cluj-Napoca")
    result = plan_fleet_routes(
        [van], [load1, load2], all_compliant([van], [load1, load2]), top_k=1,
    )
    plan = result["alternatives"][0]
    # No CHAIN plan should appear because Brasov → Constanta is too far.
    assert all(p["kind"] != "CHAIN" for p in plan["plans"])


def test_empty_fleet_returns_no_plans():
    result = plan_fleet_routes([], [make_load(10)], compliance={}, top_k=3)
    assert result["alternatives"] == []
    assert result["optimiser_status"] == "EMPTY_FLEET"

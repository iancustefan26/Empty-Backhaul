"""Unit tests for the multi-truck CP-SAT optimiser.

These tests build small synthetic (truck, load, compliance) inputs and
exercise `run_fleet_optimizer` directly — no DB, no LLM, no Sentry. They
pin the structural guarantees the rest of the system relies on:

  - one truck → at most one load
  - one load → at most one truck
  - K-best produces structurally distinct plans
  - EU 561/2006 hours-feasibility blocks impossible assignments
  - the customer-loyalty bonus only breaks ties (never sacrifices margin)
  - empty fleet / no compliant pairs → no plans, no crash
  - SLA-risk indicator (unserved customer load IDs) is populated correctly
"""
from __future__ import annotations

import pytest

from app.agents.fleet_strategist import (
    CUSTOMER_LOYALTY_BONUS_CENTS,
    run_fleet_optimizer,
)
from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_truck(id_: int, plate: str, *, lat=46.0, lon=24.0,
               remaining_h=10.0, **overrides) -> TruckSnapshot:
    base = dict(
        id=id_, plate_number=plate, carrier_name="Test",
        temp_capability="multi_temp", last_cargo="clean",
        has_pharma_logger=True, remaining_driving_hours=remaining_h,
        status="empty", current_city="Cluj", home_base_city="Bucuresti",
        lat=lat, lon=lon, wash_certificates=[],
    )
    base.update(overrides)
    return TruckSnapshot(**base)


def make_load(id_: int, *, source="customer", price=600.0,
              pickup_lat=46.0, pickup_lon=24.0,
              delivery_lat=44.4, delivery_lon=26.1,
              **overrides) -> LoadSnapshot:
    base = dict(
        id=id_, shipper_name=f"Test Shipper {id_}",
        cargo_type="dairy", cargo_description="test",
        temp_min_celsius=2.0, temp_max_celsius=6.0,
        requires_pharma_logger=False, forbidden_prior_cargo=None,
        pickup_city="Cluj", delivery_city="Bucuresti",
        pickup_lat=pickup_lat, pickup_lon=pickup_lon,
        delivery_lat=delivery_lat, delivery_lon=delivery_lon,
        pickup_window_start="2026-05-06T08:00",
        pickup_window_end="2026-05-06T18:00",
        weight_kg=8000.0, price_eur=price, status="available",
        source=source,
    )
    base.update(overrides)
    return LoadSnapshot(**base)


def compliant(truck_id: int, load_id: int) -> ComplianceVerdict:
    return ComplianceVerdict(
        load_id=load_id, is_compliant=True, confidence=0.95,
        blockers=[], warnings=[], reasoning="ok",
        cited_rule_ids=[], cited_excerpts=[], sanity_overrides=[],
    )


def blocked(load_id: int) -> ComplianceVerdict:
    return ComplianceVerdict(
        load_id=load_id, is_compliant=False, confidence=0.95,
        blockers=["test blocker"], warnings=[], reasoning="blocked",
        cited_rule_ids=[], cited_excerpts=[], sanity_overrides=[],
    )


def all_compliant(trucks, loads) -> dict[tuple[int, int], ComplianceVerdict]:
    return {(t["id"], l["id"]): compliant(t["id"], l["id"])
            for t in trucks for l in loads}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_one_load_at_most_one_truck():
    """If two trucks are both compliant for the same single load, only one
    can be assigned (no double-booking)."""
    trucks = [make_truck(1, "A"), make_truck(2, "B")]
    loads = [make_load(10, price=900.0)]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads), top_k=1)
    plan = result["alternatives"][0]
    served = [a for a in plan["assignments"] if a["load_id"] is not None]
    assert len(served) == 1
    assert plan["fleet_utilization_pct"] == pytest.approx(50.0)


def test_one_truck_at_most_one_load():
    """One truck, two compliant loads → truck takes the more profitable one."""
    trucks = [make_truck(1, "A")]
    loads = [
        make_load(10, price=400.0),
        make_load(11, price=900.0),
    ]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads), top_k=1)
    plan = result["alternatives"][0]
    served = [a for a in plan["assignments"] if a["load_id"] is not None]
    assert len(served) == 1
    assert served[0]["load_id"] == 11


def test_kbest_returns_distinct_plans():
    """Two trucks × two equally-profitable loads → K-best yields 2 distinct plans."""
    trucks = [
        make_truck(1, "A", lat=46.0, lon=24.0),
        make_truck(2, "B", lat=46.0, lon=24.0),
    ]
    loads = [
        make_load(10, price=900.0, pickup_lat=46.0, pickup_lon=24.0),
        make_load(11, price=900.0, pickup_lat=46.0, pickup_lon=24.0),
    ]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads), top_k=3)
    assert len(result["alternatives"]) >= 2
    # The two plans must differ in their assignment vector.
    plan1 = {(a["truck_id"], a["load_id"]) for a in result["alternatives"][0]["assignments"] if a["load_id"]}
    plan2 = {(a["truck_id"], a["load_id"]) for a in result["alternatives"][1]["assignments"] if a["load_id"]}
    assert plan1 != plan2


def test_hours_infeasible_blocked():
    """A truck with very few remaining driving hours can't take a long load."""
    # Truck in Cluj (lat 46.77) with 0.5h budget — round trip Cluj→Bucharest is ~7h.
    trucks = [make_truck(1, "A", lat=46.77, lon=23.62, remaining_h=0.5)]
    loads = [make_load(10, price=2000.0,
                       pickup_lat=46.77, pickup_lon=23.62,
                       delivery_lat=44.43, delivery_lon=26.10)]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads), top_k=1)
    # Either no plans returned, or the lone plan leaves the truck idle.
    if result["alternatives"]:
        plan = result["alternatives"][0]
        assert all(a["load_id"] is None for a in plan["assignments"])
    else:
        assert result["optimiser_status"] in ("NO_FEASIBLE_PAIRS", "INFEASIBLE")


def test_customer_loyalty_only_breaks_ties():
    """Two loads with identical margin — one customer, one broker. Customer wins."""
    trucks = [make_truck(1, "A")]
    loads = [
        make_load(10, source="customer", price=900.0),
        make_load(11, source="broker", price=900.0),
    ]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads),
                                  top_k=1, customer_loyalty_bonus_cents=CUSTOMER_LOYALTY_BONUS_CENTS)
    chosen = next(a for a in result["alternatives"][0]["assignments"] if a["load_id"])
    assert chosen["source"] == "customer"


def test_customer_loyalty_does_not_override_higher_margin():
    """A broker load with materially higher margin still wins over a customer load."""
    trucks = [make_truck(1, "A")]
    loads = [
        make_load(10, source="customer", price=400.0),
        make_load(11, source="broker", price=1500.0),  # broker pays much more
    ]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads), top_k=1)
    chosen = next(a for a in result["alternatives"][0]["assignments"] if a["load_id"])
    assert chosen["source"] == "broker"


def test_empty_fleet_returns_no_plans():
    result = run_fleet_optimizer([], [make_load(10)], compliance={}, top_k=3)
    assert result["alternatives"] == []
    assert result["optimiser_status"] == "EMPTY_FLEET"


def test_no_compliant_pairs_returns_no_plans():
    trucks = [make_truck(1, "A"), make_truck(2, "B")]
    loads = [make_load(10), make_load(11)]
    compliance = {(t["id"], l["id"]): blocked(l["id"]) for t in trucks for l in loads}
    result = run_fleet_optimizer(trucks, loads, compliance, top_k=3)
    assert result["alternatives"] == []
    assert result["optimiser_status"] == "NO_FEASIBLE_PAIRS"


def test_unserved_customer_load_ids_populated():
    """If 2 customer loads are available but only 1 truck, the unserved
    customer load id must appear in the SLA-risk indicator."""
    trucks = [make_truck(1, "A")]
    loads = [
        make_load(10, source="customer", price=900.0),
        make_load(11, source="customer", price=400.0),
    ]
    result = run_fleet_optimizer(trucks, loads, all_compliant(trucks, loads), top_k=1)
    plan = result["alternatives"][0]
    assert plan["customer_loads_available"] == 2
    assert plan["customer_loads_served"] == 1
    assert len(plan["unserved_customer_load_ids"]) == 1
    # The unserved one is the lower-margin (id 11).
    assert 11 in plan["unserved_customer_load_ids"]

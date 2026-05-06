"""Daily route planner for a depot-based refrigerated van company.

The carrier is based in **one** city (Cluj-Napoca by default), runs 10–15
vans, and **every van must end the day back at the depot**. The planner
schedules each van's day as either:

  - IDLE   — van stays at depot (margin = 0 €), e.g. when no profitable
             round-trip exists or compliance blocks every load
  - SINGLE — depot → pickup → delivery → depot (3 legs: empty + loaded + empty)
  - CHAIN  — depot → p1 → d1 → p2 → d2 → depot (5 legs); the 4th leg
             (delivery_1 → pickup_2) is the "between-loads deadhead" that
             a good backhaul match minimises

CP-SAT picks exactly one plan per van such that:
  - no load is double-booked across vans
  - every load assignment is HACCP/ANSVSA/GDP compliant (Analyst verdict)
  - chain legs respect dynamic compliance state — load_2 is checked
    against load_1's cargo_type as the truck's "new" last_cargo
  - the round-trip drive hours fit inside the van's EU 561/2006 budget
  - total fleet margin is maximised, with a small loyalty bonus for
    customer loads breaking ties

K-best alternative plans are produced via no-good cuts.
"""
from __future__ import annotations

import time
from typing import Literal, TypedDict

from ortools.sat.python import cp_model

from app.agents.sanity_check import (
    check_chemicals_quarantine,
    check_forbidden_prior_cargo,
    check_pharma_logger,
    check_temperature,
)
from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot
from app.services.geo import haversine_km, road_km_estimate

COST_PER_KM_EUR = 0.85
AVG_SPEED_KMH = 65.0
DRIVER_BUFFER_HOURS = 0.5
CUSTOMER_LOYALTY_BONUS_CENTS = 500
MAX_INTER_LEG_DEADHEAD_KM = 250.0   # chain pre-filter — between delivery_1 and pickup_2


# ---------------------------------------------------------------------------
# Geo + cost helpers
# ---------------------------------------------------------------------------

def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return road_km_estimate(haversine_km(lat1, lon1, lat2, lon2))


def _dist(a: dict, b: dict, *, a_field: str, b_field: str) -> float:
    """`a_field` and `b_field` each name a (lat, lon) coordinate prefix."""
    a_lat, a_lon = a[f"{a_field}_lat"], a[f"{a_field}_lon"]
    b_lat, b_lon = b[f"{b_field}_lat"], b[f"{b_field}_lon"]
    return _km(a_lat, a_lon, b_lat, b_lon)


# ---------------------------------------------------------------------------
# Plan schemas
# ---------------------------------------------------------------------------

class Leg(TypedDict):
    from_city: str
    to_city: str
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    km: float
    kind: Literal["empty", "loaded"]
    load_id: int | None       # populated for loaded legs


PlanKind = Literal["IDLE", "SINGLE", "CHAIN"]


class DayPlan(TypedDict):
    kind: PlanKind
    van_id: int
    van_plate: str
    legs: list[Leg]
    load_ids: list[int]               # 0, 1, or 2 entries
    total_km: float
    empty_km: float
    loaded_km: float
    drive_hours: float
    margin_eur: float
    margin_cents: int


class FleetPlanStats(TypedDict):
    rank: int
    objective_value_cents: int
    total_fleet_margin_eur: float
    total_loaded_km: float
    total_empty_km: float
    total_km: float
    deadhead_ratio: float
    fleet_utilization_pct: float
    single_trips_count: int
    chain_trips_count: int
    idle_count: int
    customer_loads_served: int
    customer_loads_available: int
    broker_loads_served: int
    broker_loads_available: int
    unserved_customer_load_ids: list[int]
    plans: list[DayPlan]


class RoutePlannerResult(TypedDict):
    alternatives: list[FleetPlanStats]
    optimiser_status: str
    fleet_size: int
    available_loads: int
    candidate_singles: int
    candidate_chains: int
    elapsed_ms: int
    notes: list[str]


# ---------------------------------------------------------------------------
# Compliance helpers (depot model: include dynamic state for chains)
# ---------------------------------------------------------------------------

def _truck_can_carry(truck: TruckSnapshot, load: LoadSnapshot) -> bool:
    """Hard-rule pass for the (truck, load) pair, IGNORING the compliance
    dict the caller already prepared. Used only for chain feasibility
    checks against an *intermediate* truck snapshot whose `last_cargo` =
    load_1's cargo_type.
    """
    if check_temperature(truck, load)[0] is not None:
        return False
    if check_pharma_logger(truck, load)[0] is not None:
        return False
    if check_chemicals_quarantine(truck, load)[0] is not None:
        return False
    blocker, _, _ = check_forbidden_prior_cargo(truck, load)
    return blocker is None


def _truck_after_load(truck: TruckSnapshot, load: LoadSnapshot) -> TruckSnapshot:
    """Synthetic truck snapshot AFTER it has delivered `load`. last_cargo
    becomes the load's cargo_type; current location becomes the load's
    delivery point. Used for chain feasibility checks on load_2."""
    return TruckSnapshot(
        **{**truck,
           "last_cargo": load["cargo_type"],
           "current_city": load["delivery_city"],
           "lat": load["delivery_lat"],
           "lon": load["delivery_lon"]},
    )


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------

def _idle_plan(van: TruckSnapshot) -> DayPlan:
    return DayPlan(
        kind="IDLE", van_id=van["id"], van_plate=van["plate_number"],
        legs=[], load_ids=[],
        total_km=0.0, empty_km=0.0, loaded_km=0.0, drive_hours=0.0,
        margin_eur=0.0, margin_cents=0,
    )


def _single_plan(van: TruckSnapshot, load: LoadSnapshot) -> DayPlan | None:
    leg1_km = _km(van["lat"], van["lon"], load["pickup_lat"], load["pickup_lon"])
    leg2_km = _km(load["pickup_lat"], load["pickup_lon"],
                  load["delivery_lat"], load["delivery_lon"])
    leg3_km = _km(load["delivery_lat"], load["delivery_lon"], van["lat"], van["lon"])
    total_km = leg1_km + leg2_km + leg3_km
    drive_h = total_km / AVG_SPEED_KMH
    if drive_h + DRIVER_BUFFER_HOURS > van["remaining_driving_hours"]:
        return None
    cost = COST_PER_KM_EUR * total_km
    margin = load["price_eur"] - cost
    if margin <= 0:
        return None
    legs: list[Leg] = [
        Leg(from_city=van["current_city"], to_city=load["pickup_city"],
            from_lat=van["lat"], from_lon=van["lon"],
            to_lat=load["pickup_lat"], to_lon=load["pickup_lon"],
            km=round(leg1_km, 1), kind="empty", load_id=None),
        Leg(from_city=load["pickup_city"], to_city=load["delivery_city"],
            from_lat=load["pickup_lat"], from_lon=load["pickup_lon"],
            to_lat=load["delivery_lat"], to_lon=load["delivery_lon"],
            km=round(leg2_km, 1), kind="loaded", load_id=load["id"]),
        Leg(from_city=load["delivery_city"], to_city=van["current_city"],
            from_lat=load["delivery_lat"], from_lon=load["delivery_lon"],
            to_lat=van["lat"], to_lon=van["lon"],
            km=round(leg3_km, 1), kind="empty", load_id=None),
    ]
    return DayPlan(
        kind="SINGLE", van_id=van["id"], van_plate=van["plate_number"],
        legs=legs, load_ids=[load["id"]],
        total_km=round(total_km, 1),
        empty_km=round(leg1_km + leg3_km, 1),
        loaded_km=round(leg2_km, 1),
        drive_hours=round(drive_h, 2),
        margin_eur=round(margin, 2),
        margin_cents=int(round(margin * 100)),
    )


def _chain_plan(
    van: TruckSnapshot,
    load1: LoadSnapshot, load2: LoadSnapshot,
    compliance: dict[tuple[int, int], ComplianceVerdict],
) -> DayPlan | None:
    """depot → p1 → d1 → p2 → d2 → depot (5 legs).

    Compliance pre-checks:
      - load_1 must be compliant for the original van (via `compliance` dict)
      - load_2 must be compliant for the SYNTHETIC van whose last_cargo =
        load_1's cargo_type; we run the deterministic predicates inline
        because the original `compliance` dict was built against the
        original last_cargo.
    """
    v1 = compliance.get((van["id"], load1["id"]))
    if v1 is None or not v1["is_compliant"]:
        return None
    truck_after = _truck_after_load(van, load1)
    if not _truck_can_carry(truck_after, load2):
        return None

    leg1_km = _km(van["lat"], van["lon"], load1["pickup_lat"], load1["pickup_lon"])
    leg2_km = _km(load1["pickup_lat"], load1["pickup_lon"],
                  load1["delivery_lat"], load1["delivery_lon"])
    leg3_km = _km(load1["delivery_lat"], load1["delivery_lon"],
                  load2["pickup_lat"], load2["pickup_lon"])
    if leg3_km > MAX_INTER_LEG_DEADHEAD_KM:
        return None
    leg4_km = _km(load2["pickup_lat"], load2["pickup_lon"],
                  load2["delivery_lat"], load2["delivery_lon"])
    leg5_km = _km(load2["delivery_lat"], load2["delivery_lon"], van["lat"], van["lon"])

    total_km = leg1_km + leg2_km + leg3_km + leg4_km + leg5_km
    drive_h = total_km / AVG_SPEED_KMH
    if drive_h + DRIVER_BUFFER_HOURS > van["remaining_driving_hours"]:
        return None
    cost = COST_PER_KM_EUR * total_km
    margin = (load1["price_eur"] + load2["price_eur"]) - cost
    if margin <= 0:
        return None

    legs: list[Leg] = [
        Leg(from_city=van["current_city"], to_city=load1["pickup_city"],
            from_lat=van["lat"], from_lon=van["lon"],
            to_lat=load1["pickup_lat"], to_lon=load1["pickup_lon"],
            km=round(leg1_km, 1), kind="empty", load_id=None),
        Leg(from_city=load1["pickup_city"], to_city=load1["delivery_city"],
            from_lat=load1["pickup_lat"], from_lon=load1["pickup_lon"],
            to_lat=load1["delivery_lat"], to_lon=load1["delivery_lon"],
            km=round(leg2_km, 1), kind="loaded", load_id=load1["id"]),
        Leg(from_city=load1["delivery_city"], to_city=load2["pickup_city"],
            from_lat=load1["delivery_lat"], from_lon=load1["delivery_lon"],
            to_lat=load2["pickup_lat"], to_lon=load2["pickup_lon"],
            km=round(leg3_km, 1), kind="empty", load_id=None),
        Leg(from_city=load2["pickup_city"], to_city=load2["delivery_city"],
            from_lat=load2["pickup_lat"], from_lon=load2["pickup_lon"],
            to_lat=load2["delivery_lat"], to_lon=load2["delivery_lon"],
            km=round(leg4_km, 1), kind="loaded", load_id=load2["id"]),
        Leg(from_city=load2["delivery_city"], to_city=van["current_city"],
            from_lat=load2["delivery_lat"], from_lon=load2["delivery_lon"],
            to_lat=van["lat"], to_lon=van["lon"],
            km=round(leg5_km, 1), kind="empty", load_id=None),
    ]
    empty_km = leg1_km + leg3_km + leg5_km
    loaded_km = leg2_km + leg4_km
    return DayPlan(
        kind="CHAIN", van_id=van["id"], van_plate=van["plate_number"],
        legs=legs, load_ids=[load1["id"], load2["id"]],
        total_km=round(total_km, 1),
        empty_km=round(empty_km, 1),
        loaded_km=round(loaded_km, 1),
        drive_hours=round(drive_h, 2),
        margin_eur=round(margin, 2),
        margin_cents=int(round(margin * 100)),
    )


# ---------------------------------------------------------------------------
# Solver entrypoint
# ---------------------------------------------------------------------------

def plan_fleet_routes(
    vans: list[TruckSnapshot],
    loads: list[LoadSnapshot],
    compliance: dict[tuple[int, int], ComplianceVerdict],
    *,
    top_k: int = 3,
    customer_loyalty_bonus_cents: int = CUSTOMER_LOYALTY_BONUS_CENTS,
    enable_chains: bool = True,
) -> RoutePlannerResult:
    started = time.perf_counter()
    notes: list[str] = []

    if not vans:
        return RoutePlannerResult(
            alternatives=[], optimiser_status="EMPTY_FLEET",
            fleet_size=0, available_loads=len(loads),
            candidate_singles=0, candidate_chains=0,
            elapsed_ms=0, notes=["no vans available"],
        )

    customer_load_ids = {l["id"] for l in loads if l.get("source") == "customer"}
    broker_load_ids = {l["id"] for l in loads if l.get("source") == "broker"}

    # ----- Build candidate plans per van -----
    plans_by_van: dict[int, list[DayPlan]] = {v["id"]: [_idle_plan(v)] for v in vans}
    candidate_singles = 0
    candidate_chains = 0

    for v in vans:
        for l in loads:
            verdict = compliance.get((v["id"], l["id"]))
            if verdict is None or not verdict["is_compliant"]:
                continue
            single = _single_plan(v, l)
            if single is not None:
                plans_by_van[v["id"]].append(single)
                candidate_singles += 1

        if enable_chains:
            # Only consider chains using loads compliant for the original van.
            base_loads = [
                l for l in loads
                if (verdict := compliance.get((v["id"], l["id"]))) is not None
                and verdict["is_compliant"]
            ]
            for l1 in base_loads:
                for l2 in base_loads:
                    if l1["id"] == l2["id"]:
                        continue
                    chain = _chain_plan(v, l1, l2, compliance)
                    if chain is not None:
                        plans_by_van[v["id"]].append(chain)
                        candidate_chains += 1

    total_candidates = sum(len(p) for p in plans_by_van.values())
    if total_candidates == len(vans):  # only IDLE plans
        return RoutePlannerResult(
            alternatives=[FleetPlanStats(
                rank=1, objective_value_cents=0,
                total_fleet_margin_eur=0.0, total_loaded_km=0.0, total_empty_km=0.0,
                total_km=0.0, deadhead_ratio=0.0, fleet_utilization_pct=0.0,
                single_trips_count=0, chain_trips_count=0, idle_count=len(vans),
                customer_loads_served=0, customer_loads_available=len(customer_load_ids),
                broker_loads_served=0, broker_loads_available=len(broker_load_ids),
                unserved_customer_load_ids=sorted(customer_load_ids),
                plans=[plans_by_van[v["id"]][0] for v in vans],
            )],
            optimiser_status="ALL_IDLE",
            fleet_size=len(vans), available_loads=len(loads),
            candidate_singles=0, candidate_chains=0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            notes=["no profitable round-trip exists for any van today"],
        )

    # ----- CP-SAT model -----
    alternatives: list[FleetPlanStats] = []
    forbidden_assignment_keys: list[set[tuple[int, int]]] = []
    final_status = "OPTIMAL"

    # Stable index of every (van, plan) candidate
    flat_plans: list[tuple[int, DayPlan]] = []
    for v in vans:
        for p in plans_by_van[v["id"]]:
            flat_plans.append((v["id"], p))
    plan_idx_by_load: dict[int, list[int]] = {}
    for i, (_, p) in enumerate(flat_plans):
        for lid in p["load_ids"]:
            plan_idx_by_load.setdefault(lid, []).append(i)
    plan_idx_by_van: dict[int, list[int]] = {}
    for i, (vid, _) in enumerate(flat_plans):
        plan_idx_by_van.setdefault(vid, []).append(i)

    def assignment_key(plan: DayPlan) -> tuple[int, int]:
        # A plan is uniquely identified by (van_id, sorted-tuple of load_ids).
        # IDLE → (van_id, ()); SINGLE → (van_id, (load,)); CHAIN → (van_id,
        # (load_a, load_b)).
        return (plan["van_id"], tuple(sorted(plan["load_ids"])))  # type: ignore[return-value]

    for rank in range(1, top_k + 1):
        model = cp_model.CpModel()
        x = [model.NewBoolVar(f"y_{i}") for i in range(len(flat_plans))]

        # Exactly one plan per van.
        for vid, idxs in plan_idx_by_van.items():
            model.Add(sum(x[i] for i in idxs) == 1)

        # Each load assigned at most once across all plans.
        for lid, idxs in plan_idx_by_load.items():
            if len(idxs) > 1:
                model.Add(sum(x[i] for i in idxs) <= 1)

        # No-good cuts excluding earlier alternatives.
        for prev in forbidden_assignment_keys:
            same_indices = [
                i for i, (_, p) in enumerate(flat_plans)
                if assignment_key(p) in prev
            ]
            if same_indices:
                model.Add(sum(x[i] for i in same_indices) <= len(same_indices) - 1)

        # Objective: margin in cents + customer loyalty bonus per
        # CUSTOMER load served by the chosen plan.
        objective_terms = []
        for i, (_, p) in enumerate(flat_plans):
            term = p["margin_cents"]
            term += customer_loyalty_bonus_cents * sum(
                1 for lid in p["load_ids"] if lid in customer_load_ids
            )
            objective_terms.append(term * x[i])
        model.Maximize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 8.0
        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            final_status = status_name if rank == 1 else "EXHAUSTED"
            break

        chosen_plans: list[DayPlan] = []
        for i, (_, p) in enumerate(flat_plans):
            if solver.Value(x[i]) == 1:
                chosen_plans.append(p)

        # Compute per-fleet stats
        total_loaded = sum(p["loaded_km"] for p in chosen_plans)
        total_empty = sum(p["empty_km"] for p in chosen_plans)
        total_km = total_loaded + total_empty
        served_loads: set[int] = set()
        for p in chosen_plans:
            served_loads.update(p["load_ids"])
        served_customer = len(served_loads & customer_load_ids)
        served_broker = len(served_loads & broker_load_ids)
        unserved_customer = sorted(customer_load_ids - served_loads)
        single_trips = sum(1 for p in chosen_plans if p["kind"] == "SINGLE")
        chain_trips = sum(1 for p in chosen_plans if p["kind"] == "CHAIN")
        idle = sum(1 for p in chosen_plans if p["kind"] == "IDLE")
        utilisation = (len(chosen_plans) - idle) / len(vans) * 100

        alternatives.append(FleetPlanStats(
            rank=rank,
            objective_value_cents=int(solver.ObjectiveValue()),
            total_fleet_margin_eur=round(sum(p["margin_eur"] for p in chosen_plans), 2),
            total_loaded_km=round(total_loaded, 1),
            total_empty_km=round(total_empty, 1),
            total_km=round(total_km, 1),
            deadhead_ratio=round(total_empty / total_km, 4) if total_km else 0.0,
            fleet_utilization_pct=round(utilisation, 1),
            single_trips_count=single_trips,
            chain_trips_count=chain_trips,
            idle_count=idle,
            customer_loads_served=served_customer,
            customer_loads_available=len(customer_load_ids),
            broker_loads_served=served_broker,
            broker_loads_available=len(broker_load_ids),
            unserved_customer_load_ids=unserved_customer,
            plans=chosen_plans,
        ))
        forbidden_assignment_keys.append({assignment_key(p) for p in chosen_plans})

    return RoutePlannerResult(
        alternatives=alternatives,
        optimiser_status=final_status,
        fleet_size=len(vans),
        available_loads=len(loads),
        candidate_singles=candidate_singles,
        candidate_chains=candidate_chains,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        notes=notes,
    )

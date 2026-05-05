"""Fleet-level Strategist.

Generalises the single-truck pick-one (`app/agents/strategist.py`) into a
multi-truck assignment problem solved by OR-Tools CP-SAT:

  Variables:    x_{t,l} ∈ {0,1}  for every (truck, load) pair where the
                Analyst declared the pair compliant AND the truck has the
                driving-hours budget to do the trip.
  Constraints:  Σ_l x_{t,l} ≤ 1   ∀t   (each truck takes at most one load)
                Σ_t x_{t,l} ≤ 1   ∀l   (each load served by at most one truck)
  Objective:    max  Σ margin_{t,l} × x_{t,l}  +  α × is_customer_load_l × x_{t,l}
                where margin = price − cost_per_km × (empty_km + loaded_km)
                and α is a small loyalty bonus that breaks ties in favour of
                serving direct-customer loads over spot freight.

K-best alternatives are produced by adding a "no-good cut" after each solve
that excludes the previously-found assignment vector, then re-solving. The
result is an ordered list of structurally-distinct plans P1, P2, P3 sorted
by total objective value.

Per-plan stats include the metrics a dispatcher (and a thesis evaluator)
actually cares about: total margin, deadhead ratio, fleet utilisation,
served-customer-load count, unserved-customer-load IDs (SLA risk).
"""
from __future__ import annotations

import time
from typing import TypedDict

from ortools.sat.python import cp_model

from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot
from app.services.geo import haversine_km, road_km_estimate

COST_PER_KM_EUR = 0.85
AVG_SPEED_KMH = 65.0           # for EU 561/2006 hours-feasibility check
DRIVER_BUFFER_HOURS = 0.5       # mandatory rest + admin buffer
CUSTOMER_LOYALTY_BONUS_CENTS = 500   # 5 € per customer load to break ties


# ---------------------------------------------------------------------------
# Per-pair scoring (mirrors single-truck strategist; kept local so the two
# strategists can evolve independently if cost models diverge later).
# ---------------------------------------------------------------------------

class PairScore(TypedDict):
    truck_plate: str
    truck_id: int
    load_id: int
    cargo_type: str
    source: str | None              # "customer" | "broker" | None
    route: str
    empty_km: float
    loaded_km: float
    total_km: float
    drive_hours: float
    cost_eur: float
    price_eur: float
    margin_eur: float
    margin_cents: int
    hours_feasible: bool


def score_pair(truck: TruckSnapshot, load: LoadSnapshot) -> PairScore:
    empty_km = road_km_estimate(haversine_km(
        truck["lat"], truck["lon"], load["pickup_lat"], load["pickup_lon"],
    ))
    loaded_km = road_km_estimate(haversine_km(
        load["pickup_lat"], load["pickup_lon"],
        load["delivery_lat"], load["delivery_lon"],
    ))
    cost = COST_PER_KM_EUR * (empty_km + loaded_km)
    margin = load["price_eur"] - cost
    drive_h = (empty_km + loaded_km) / AVG_SPEED_KMH
    hours_feasible = (
        drive_h + DRIVER_BUFFER_HOURS <= truck["remaining_driving_hours"]
    )
    return PairScore(
        truck_plate=truck["plate_number"],
        truck_id=truck["id"],
        load_id=load["id"],
        cargo_type=load["cargo_type"],
        source=load.get("source"),
        route=f"{load['pickup_city']}->{load['delivery_city']}",
        empty_km=round(empty_km, 1),
        loaded_km=round(loaded_km, 1),
        total_km=round(empty_km + loaded_km, 1),
        drive_hours=round(drive_h, 2),
        cost_eur=round(cost, 2),
        price_eur=load["price_eur"],
        margin_eur=round(margin, 2),
        margin_cents=int(round(margin * 100)),
        hours_feasible=hours_feasible,
    )


# ---------------------------------------------------------------------------
# Fleet plan + per-plan stats
# ---------------------------------------------------------------------------

class TruckAssignment(TypedDict):
    truck_id: int
    truck_plate: str
    truck_current_city: str
    load_id: int | None
    load_pickup_city: str | None
    load_delivery_city: str | None
    cargo_type: str | None
    source: str | None
    empty_km: float
    loaded_km: float
    drive_hours: float
    margin_eur: float


class FleetPlanStats(TypedDict):
    rank: int                           # 1 = best plan, 2 = second best, ...
    objective_value_cents: int
    total_margin_eur: float
    total_loaded_km: float
    total_empty_km: float
    total_km: float
    deadhead_ratio: float               # empty / (empty + loaded); 0 if no movement
    fleet_utilization_pct: float        # trucks_assigned / trucks_total
    customer_loads_served: int
    customer_loads_available: int
    broker_loads_served: int
    broker_loads_available: int
    unserved_customer_load_ids: list[int]
    assignments: list[TruckAssignment]


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

class FleetStrategistResult(TypedDict):
    alternatives: list[FleetPlanStats]
    optimiser_status: str
    fleet_size: int
    available_loads: int
    candidate_pairs: int                # truck × load pairs after compliance + hours filter
    elapsed_ms: int
    notes: list[str]


def run_fleet_optimizer(
    trucks: list[TruckSnapshot],
    loads: list[LoadSnapshot],
    compliance: dict[tuple[int, int], ComplianceVerdict],
    *,
    top_k: int = 3,
    customer_loyalty_bonus_cents: int = CUSTOMER_LOYALTY_BONUS_CENTS,
) -> FleetStrategistResult:
    """Run the multi-truck CP-SAT assignment, returning the top-K plans.

    Args:
        trucks: empty trucks available for dispatch (deduped by id).
        loads: available backhaul loads.
        compliance: dict keyed by (truck_id, load_id) → verdict from the
            Analyst. Pairs missing from this dict are treated as
            non-compliant.
        top_k: number of alternative plans to enumerate.
        customer_loyalty_bonus_cents: small bias added to customer loads in
            the objective so tied plans prefer serving the contracted book.

    Returns:
        FleetStrategistResult with `alternatives` sorted by objective DESC.
    """
    started = time.perf_counter()
    notes: list[str] = []

    if not trucks:
        return FleetStrategistResult(
            alternatives=[], optimiser_status="EMPTY_FLEET",
            fleet_size=0, available_loads=len(loads),
            candidate_pairs=0, elapsed_ms=0,
            notes=["no trucks available"],
        )

    customer_load_ids = {l["id"] for l in loads if l.get("source") == "customer"}
    broker_load_ids = {l["id"] for l in loads if l.get("source") == "broker"}
    loads_by_id = {l["id"]: l for l in loads}

    # 1. Build the candidate-pair table (compliant + hours feasible + positive margin).
    pairs: list[PairScore] = []
    for t in trucks:
        for l in loads:
            v = compliance.get((t["id"], l["id"]))
            if v is None or not v["is_compliant"]:
                continue
            score = score_pair(t, l)
            if not score["hours_feasible"]:
                continue
            if score["margin_eur"] <= 0:
                # Driving empty is cheaper than a money-losing assignment.
                continue
            pairs.append(score)

    if not pairs:
        return FleetStrategistResult(
            alternatives=[], optimiser_status="NO_FEASIBLE_PAIRS",
            fleet_size=len(trucks), available_loads=len(loads),
            candidate_pairs=0, elapsed_ms=int((time.perf_counter() - started) * 1000),
            notes=["no compliant + hours-feasible + profitable (truck, load) pairs"],
        )

    # 2. CP-SAT model.
    alternatives: list[FleetPlanStats] = []
    forbidden_assignments: list[set[tuple[int, int]]] = []  # for no-good cuts
    final_status = "OPTIMAL"

    for rank in range(1, top_k + 1):
        model = cp_model.CpModel()
        x = {}
        for i, p in enumerate(pairs):
            x[i] = model.NewBoolVar(f"x_{p['truck_id']}_{p['load_id']}")

        # one-load-per-truck
        for t in trucks:
            xs = [x[i] for i, p in enumerate(pairs) if p["truck_id"] == t["id"]]
            if xs:
                model.Add(sum(xs) <= 1)

        # one-truck-per-load
        for lid in {p["load_id"] for p in pairs}:
            xs = [x[i] for i, p in enumerate(pairs) if p["load_id"] == lid]
            if len(xs) > 1:
                model.Add(sum(xs) <= 1)

        # No-good cuts: each previously-chosen plan must differ from this one.
        # If a plan chose pairs S, then we forbid x being a superset of S
        # (i.e., at least one of those vars must flip to 0).
        for prev_assignment in forbidden_assignments:
            prev_indices = [
                i for i, p in enumerate(pairs)
                if (p["truck_id"], p["load_id"]) in prev_assignment
            ]
            if prev_indices:
                model.Add(sum(x[i] for i in prev_indices) <= len(prev_indices) - 1)

        # Objective: margin in cents + customer loyalty bonus per assignment.
        objective_terms = []
        for i, p in enumerate(pairs):
            term = p["margin_cents"]
            if p["load_id"] in customer_load_ids:
                term += customer_loyalty_bonus_cents
            objective_terms.append(term * x[i])
        model.Maximize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        status = solver.Solve(model)
        status_name = solver.StatusName(status)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if rank == 1:
                final_status = status_name
            else:
                # Out of distinct plans — stop early.
                final_status = "EXHAUSTED" if alternatives else status_name
            break

        chosen_pairs = [
            (pairs[i]["truck_id"], pairs[i]["load_id"])
            for i in x
            if solver.Value(x[i]) == 1
        ]
        if not chosen_pairs:
            # All-zero solution (everything money-losing or forbidden); record once.
            if rank == 1:
                notes.append("optimiser returned the empty plan as best")
            break

        # Build the per-truck assignment table for this plan.
        assigned_by_truck: dict[int, int] = {tid: lid for tid, lid in chosen_pairs}
        assignments: list[TruckAssignment] = []
        for t in trucks:
            lid = assigned_by_truck.get(t["id"])
            if lid is None:
                assignments.append(TruckAssignment(
                    truck_id=t["id"], truck_plate=t["plate_number"],
                    truck_current_city=t["current_city"],
                    load_id=None, load_pickup_city=None, load_delivery_city=None,
                    cargo_type=None, source=None,
                    empty_km=0.0, loaded_km=0.0, drive_hours=0.0, margin_eur=0.0,
                ))
                continue
            score = next(
                p for p in pairs
                if p["truck_id"] == t["id"] and p["load_id"] == lid
            )
            load = loads_by_id[lid]
            assignments.append(TruckAssignment(
                truck_id=t["id"], truck_plate=t["plate_number"],
                truck_current_city=t["current_city"],
                load_id=lid,
                load_pickup_city=load["pickup_city"],
                load_delivery_city=load["delivery_city"],
                cargo_type=load["cargo_type"],
                source=load.get("source"),
                empty_km=score["empty_km"],
                loaded_km=score["loaded_km"],
                drive_hours=score["drive_hours"],
                margin_eur=score["margin_eur"],
            ))

        total_loaded = sum(a["loaded_km"] for a in assignments)
        total_empty = sum(a["empty_km"] for a in assignments)
        total_km = total_loaded + total_empty
        served_customer = sum(
            1 for a in assignments
            if a["load_id"] is not None and a["source"] == "customer"
        )
        served_broker = sum(
            1 for a in assignments
            if a["load_id"] is not None and a["source"] == "broker"
        )
        unserved_customer = sorted(customer_load_ids - {a["load_id"] for a in assignments if a["load_id"]})
        utilisation = (
            sum(1 for a in assignments if a["load_id"] is not None) / len(trucks) * 100
        )

        plan = FleetPlanStats(
            rank=rank,
            objective_value_cents=int(solver.ObjectiveValue()),
            total_margin_eur=round(sum(a["margin_eur"] for a in assignments), 2),
            total_loaded_km=round(total_loaded, 1),
            total_empty_km=round(total_empty, 1),
            total_km=round(total_km, 1),
            deadhead_ratio=round(total_empty / total_km, 4) if total_km else 0.0,
            fleet_utilization_pct=round(utilisation, 1),
            customer_loads_served=served_customer,
            customer_loads_available=len(customer_load_ids),
            broker_loads_served=served_broker,
            broker_loads_available=len(broker_load_ids),
            unserved_customer_load_ids=unserved_customer,
            assignments=assignments,
        )
        alternatives.append(plan)
        forbidden_assignments.append(set(chosen_pairs))

    return FleetStrategistResult(
        alternatives=alternatives,
        optimiser_status=final_status,
        fleet_size=len(trucks),
        available_loads=len(loads),
        candidate_pairs=len(pairs),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        notes=notes,
    )

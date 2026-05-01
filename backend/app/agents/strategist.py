"""Agent 3 — Strategist.

Takes the compliant subset of loads and runs a CP-SAT model that maximises
total expected margin under a "pick at most one load" constraint. The
formulation generalises trivially to multi-truck assignment in a later phase.
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from app.agents.state import StrategistDecision, WorkflowState
from app.services.geo import haversine_km, road_km_estimate

COST_PER_KM_EUR = 0.85  # all-in EU reefer cost (fuel + driver + maintenance)


def _score_load(truck, load) -> dict:
    empty_km = road_km_estimate(haversine_km(
        truck["lat"], truck["lon"], load["pickup_lat"], load["pickup_lon"]
    ))
    loaded_km = road_km_estimate(haversine_km(
        load["pickup_lat"], load["pickup_lon"], load["delivery_lat"], load["delivery_lon"]
    ))
    cost = COST_PER_KM_EUR * (empty_km + loaded_km)
    margin = load["price_eur"] - cost
    return {
        "load_id": load["id"],
        "cargo_type": load["cargo_type"],
        "route": f"{load['pickup_city']}->{load['delivery_city']}",
        "empty_detour_km": round(empty_km, 1),
        "loaded_km": round(loaded_km, 1),
        "price_eur": load["price_eur"],
        "estimated_cost_eur": round(cost, 2),
        "expected_margin_eur": round(margin, 2),
    }


def strategist_node(state: WorkflowState) -> dict:
    truck = state["truck"]
    verdicts = state.get("compliance_results", [])
    loads_by_id = {l["id"]: l for l in state.get("available_loads", [])}

    compliant_pairs = [
        (v, loads_by_id[v["load_id"]])
        for v in verdicts
        if v["is_compliant"] and v["load_id"] in loads_by_id
    ]
    rejected_pairs = [
        (v, loads_by_id[v["load_id"]])
        for v in verdicts
        if not v["is_compliant"] and v["load_id"] in loads_by_id
    ]

    full_table = []
    for verdict, load in compliant_pairs + rejected_pairs:
        scored = _score_load(truck, load)
        scored["compliant"] = verdict["is_compliant"]
        scored["primary_blocker"] = verdict["blockers"][0] if verdict["blockers"] else None
        full_table.append(scored)
    full_table.sort(key=lambda r: (-r["compliant"], -r["expected_margin_eur"]))

    if not compliant_pairs:
        return {"decision": StrategistDecision(
            chosen_load_id=None, chosen_load=None,
            expected_margin_eur=None, empty_detour_km=None, loaded_km=None,
            score_table=full_table,
            optimiser_status="NO_COMPLIANT_LOADS",
            explanation=(
                f"Truck {truck['plate_number']} (last_cargo={truck['last_cargo']}, "
                f"capability={truck['temp_capability']}) has no compliant backhaul "
                f"candidates among {len(verdicts)} available loads."
            ),
        ), "strategist_log": {"considered": len(verdicts), "compliant": 0}}

    # Build CP-SAT.
    model = cp_model.CpModel()
    n = len(compliant_pairs)
    x = [model.NewBoolVar(f"x_{i}") for i in range(n)]

    # Pre-compute per-candidate scores in integer cents.
    candidate_scores = []
    for _, load in compliant_pairs:
        scored = _score_load(truck, load)
        candidate_scores.append(scored)
    margins_cents = [int(round(s["expected_margin_eur"] * 100)) for s in candidate_scores]

    # At most one load per truck (foundation for multi-truck assignment later).
    model.Add(sum(x) <= 1)

    # Objective: maximise the chosen margin.
    model.Maximize(sum(m * v for m, v in zip(margins_cents, x)))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"decision": StrategistDecision(
            chosen_load_id=None, chosen_load=None,
            expected_margin_eur=None, empty_detour_km=None, loaded_km=None,
            score_table=full_table,
            optimiser_status=status_name,
            explanation=f"OR-Tools returned {status_name}; no assignment chosen.",
        ), "strategist_log": {"considered": len(verdicts), "compliant": n,
                              "optimiser_status": status_name}}

    chosen_idx = next((i for i in range(n) if solver.Value(x[i]) == 1), None)
    if chosen_idx is None:
        # All margins were non-positive -> better to stay empty.
        return {"decision": StrategistDecision(
            chosen_load_id=None, chosen_load=None,
            expected_margin_eur=None, empty_detour_km=None, loaded_km=None,
            score_table=full_table,
            optimiser_status="ALL_NEGATIVE_MARGIN",
            explanation=(
                "All compliant loads had non-positive expected margin after deadhead and "
                "loaded-km costs. Recommend dispatching the truck home empty."
            ),
        ), "strategist_log": {"considered": len(verdicts), "compliant": n}}

    chosen_verdict, chosen_load = compliant_pairs[chosen_idx]
    chosen_score = candidate_scores[chosen_idx]

    # Margin lift over the next-best alternative is handy thesis colour.
    runner_up = sorted(
        (s for s in candidate_scores if s["load_id"] != chosen_load["id"]),
        key=lambda s: -s["expected_margin_eur"],
    )
    runner_up_margin = runner_up[0]["expected_margin_eur"] if runner_up else None

    explanation_lines = [
        f"Optimiser chose load #{chosen_load['id']} ({chosen_load['cargo_type']}) "
        f"on {chosen_score['route']}.",
        f"Empty deadhead {chosen_score['empty_detour_km']} km + loaded {chosen_score['loaded_km']} km "
        f"= EUR {chosen_score['estimated_cost_eur']} cost vs EUR {chosen_score['price_eur']} price -> "
        f"margin EUR {chosen_score['expected_margin_eur']}.",
    ]
    if runner_up_margin is not None:
        explanation_lines.append(
            f"Lift over best alternative: EUR {round(chosen_score['expected_margin_eur'] - runner_up_margin, 2)}."
        )

    return {
        "decision": StrategistDecision(
            chosen_load_id=chosen_load["id"],
            chosen_load=chosen_load,
            expected_margin_eur=chosen_score["expected_margin_eur"],
            empty_detour_km=chosen_score["empty_detour_km"],
            loaded_km=chosen_score["loaded_km"],
            score_table=full_table,
            optimiser_status=status_name,
            explanation=" ".join(explanation_lines),
        ),
        "strategist_log": {
            "considered": len(verdicts),
            "compliant": n,
            "optimiser_status": status_name,
            "objective_value_cents": solver.ObjectiveValue(),
            "chosen_load_id": chosen_load["id"],
        },
    }

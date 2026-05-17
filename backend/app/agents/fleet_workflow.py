"""Fleet workflow — Sentry-fleet → Analyst-fleet → Fleet Strategist.

The single-truck workflow (`workflow.py`) hydrates one truck at a time and
asks the Strategist to pick at most one load. The fleet workflow does the
same end-to-end but for the WHOLE fleet of empty trucks at once, then asks
the multi-truck CP-SAT optimiser for the top-K alternative assignments.

Why this is its own workflow rather than a loop over the single-truck one:

  - We need the FULL compliance matrix (every truck × every load) so the
    optimiser can swap assignments globally — not greedy per-truck.
  - We want one Sentry hit (one DB roundtrip per table), not N.
  - We want one shared LLM cache pass so identical (truck, load) prompts
    reuse the same Gemini response across the whole fleet.

The Analyst remains a per-pair loop (it inspects the truck and load
together to write a verdict), but it's batched by the workflow and gates
LLM calls behind the same disk cache used elsewhere.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, TypedDict

from sqlalchemy import text

from app.agents.analyst import (
    _SYSTEM_PROMPT, _build_query, _build_user_message, _evaluate_mock,
    _parse_verdict,
)
from app.agents.fleet_strategist import FleetStrategistResult, run_fleet_optimizer
from app.agents.llm_provider import LLMProvider, MockProvider, get_provider
from app.agents.sanity_check import apply_sanity_layer, hard_rules_verdict
from app.agents.sentry import _row_to_load, _row_to_truck
from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot
from app.core.database import SessionLocal
from app.rag.ingest import query_corpus, query_rules

MAX_FLEET_SIZE = 25


_FLEET_TRUCKS_SQL = text("""
    SELECT id, plate_number, carrier_name, temp_capability, last_cargo,
           has_pharma_logger, remaining_driving_hours, status,
           current_city, home_base_city,
           ST_Y(current_location::geometry) AS lat,
           ST_X(current_location::geometry) AS lon
    FROM trucks
    WHERE status = 'empty'
    ORDER BY id
    LIMIT :limit
""")

_WASH_BY_TRUCK_SQL = text("""
    SELECT truck_id, certificate_number, issued_at, valid_until, wash_type,
           prior_cargo, issuing_facility
    FROM wash_certificates
    WHERE truck_id = ANY(:truck_ids)
""")

_FLEET_LOADS_SQL = text("""
    SELECT id, shipper_name, cargo_type, cargo_description,
           temp_min_celsius, temp_max_celsius, requires_pharma_logger,
           forbidden_prior_cargo,
           pickup_city, delivery_city,
           ST_Y(pickup_location::geometry)   AS pickup_lat,
           ST_X(pickup_location::geometry)   AS pickup_lon,
           ST_Y(delivery_location::geometry) AS delivery_lat,
           ST_X(delivery_location::geometry) AS delivery_lon,
           pickup_window_start, pickup_window_end,
           weight_kg, price_eur, status, source
    FROM load_requests
    WHERE status = 'available' AND pickup_window_end >= :now
      AND (:include_broker OR source = 'customer')
    ORDER BY id
""")


class FleetWorkflowResult(TypedDict):
    fleet: list[TruckSnapshot]
    available_loads: list[LoadSnapshot]
    sentry_log: dict[str, Any]
    compliance: dict[tuple[int, int], ComplianceVerdict]   # (truck_id, load_id) -> verdict
    analyst_log: dict[str, Any]
    optimiser: FleetStrategistResult
    error: str | None


# ---------------------------------------------------------------------------
# Sentry-fleet
# ---------------------------------------------------------------------------

def sentry_fleet(*, include_broker: bool = True, fleet_size: int = MAX_FLEET_SIZE) -> dict:
    if SessionLocal is None:
        return {"error": "SUPABASE_DATABASE_URL is not configured"}

    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        truck_rows = session.execute(_FLEET_TRUCKS_SQL, {"limit": fleet_size}).all()
        if not truck_rows:
            return {"error": "no empty trucks in the fleet right now"}

        truck_ids = [r.id for r in truck_rows]
        wash_rows = session.execute(_WASH_BY_TRUCK_SQL, {"truck_ids": truck_ids}).all()

        load_rows = session.execute(_FLEET_LOADS_SQL, {
            "now": now, "include_broker": include_broker,
        }).all()

    washes_by_truck: dict[int, list[dict]] = {tid: [] for tid in truck_ids}
    for w in wash_rows:
        washes_by_truck[w.truck_id].append({
            "certificate_number": w.certificate_number,
            "issued_at": w.issued_at.isoformat(),
            "valid_until": w.valid_until.isoformat(),
            "wash_type": w.wash_type,
            "prior_cargo": w.prior_cargo,
            "issuing_facility": w.issuing_facility,
            "is_currently_valid": w.issued_at <= now <= w.valid_until,
        })

    fleet = [_row_to_truck(r, washes_by_truck.get(r.id, [])) for r in truck_rows]
    loads = [_row_to_load(r) for r in load_rows]

    customer_loads = sum(1 for l in loads if l.get("source") == "customer")
    broker_loads = sum(1 for l in loads if l.get("source") == "broker")

    sentry_log = {
        "fleet_size": len(fleet),
        "available_load_count": len(loads),
        "customer_loads": customer_loads,
        "broker_loads": broker_loads,
        "include_broker": include_broker,
        "monitored_at": now.isoformat(),
    }
    return {
        "fleet": fleet, "available_loads": loads, "sentry_log": sentry_log,
    }


# ---------------------------------------------------------------------------
# Analyst-fleet — full compliance matrix with hard-rule pre-filter
# ---------------------------------------------------------------------------

def analyst_fleet(
    fleet: list[TruckSnapshot],
    loads: list[LoadSnapshot],
    *,
    use_mock_llm: bool = True,
) -> tuple[dict[tuple[int, int], ComplianceVerdict], dict[str, Any]]:
    """For every (truck, load) pair, produce a ComplianceVerdict.

    Hard-rule pre-filter: pairs the deterministic checker says are
    *blocked* skip the LLM entirely (we trust the hard rules and save the
    Gemini call). Pairs the deterministic checker says are *compliant*
    still go to the LLM in non-mock mode for the citation/reasoning, then
    pass through `apply_sanity_layer` as in the single-truck path.
    """
    started = time.perf_counter()
    provider = MockProvider() if use_mock_llm else get_provider()
    use_mock = isinstance(provider, MockProvider)

    compliance: dict[tuple[int, int], ComplianceVerdict] = {}
    pre_blocked = 0
    rag_hits = 0
    corpus_hits = 0
    llm_calls = 0
    cache_hits = 0
    parse_errors = 0
    sanity_corrections = 0

    for t in fleet:
        for l in loads:
            hard = hard_rules_verdict(t, l)
            if not hard["is_compliant"]:
                # Deterministic fail-fast — skip the LLM, mock the verdict
                # straight from the hard rules. Cheaper than a Gemini call,
                # equally trustworthy (the LLM would have either agreed or
                # been overridden by the sanity layer anyway).
                compliance[(t["id"], l["id"])] = _evaluate_mock(t, l)
                pre_blocked += 1
                continue

            if use_mock:
                compliance[(t["id"], l["id"])] = _evaluate_mock(t, l)
                continue

            # Compliant on hard rules → consult the LLM for citations + reasoning,
            # then sanity-layer for safety.
            query = _build_query(t, l)
            rules = query_rules(query, k=5)
            excerpts = query_corpus(query, k=3)
            rag_hits += len(rules)
            corpus_hits += len(excerpts)
            try:
                raw, was_cached = provider.evaluate(
                    _SYSTEM_PROMPT,
                    _build_user_message(t, l, rules, excerpts),
                )
                if was_cached:
                    cache_hits += 1
                else:
                    llm_calls += 1
                llm_v = _parse_verdict(raw, l["id"], excerpts)
                verdict, overrides = apply_sanity_layer(llm_v, hard, t, l)
                if overrides:
                    sanity_corrections += 1
            except Exception as exc:
                parse_errors += 1
                # Fall back to the hard-rules verdict.
                verdict = _evaluate_mock(t, l)
            compliance[(t["id"], l["id"])] = verdict

    log = {
        "mode": provider.name,
        "model": None if use_mock else f"{provider.name}:{provider.model}",
        "fleet_size": len(fleet),
        "load_count": len(loads),
        "pair_count": len(fleet) * len(loads),
        "pre_blocked_pairs": pre_blocked,
        "compliant_pairs": sum(1 for v in compliance.values() if v["is_compliant"]),
        "rag_hits": rag_hits,
        "corpus_hits": corpus_hits,
        "llm_calls": llm_calls,
        "cache_hits": cache_hits,
        "parse_errors": parse_errors,
        "sanity_corrections": sanity_corrections,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    return compliance, log


# ---------------------------------------------------------------------------
# End-to-end fleet match
# ---------------------------------------------------------------------------

def run_fleet_match(
    *,
    top_k: int = 3,
    include_broker: bool = True,
    use_mock_llm: bool = True,
    fleet_size: int = MAX_FLEET_SIZE,
) -> FleetWorkflowResult:
    sentry_out = sentry_fleet(include_broker=include_broker, fleet_size=fleet_size)
    if "error" in sentry_out:
        return FleetWorkflowResult(
            fleet=[], available_loads=[], sentry_log={},
            compliance={}, analyst_log={},
            optimiser=FleetStrategistResult(
                alternatives=[], optimiser_status="ERROR",
                fleet_size=0, available_loads=0, candidate_pairs=0,
                elapsed_ms=0, notes=[],
            ),
            error=sentry_out["error"],
        )

    fleet = sentry_out["fleet"]
    loads = sentry_out["available_loads"]
    sentry_log = sentry_out["sentry_log"]

    compliance, analyst_log = analyst_fleet(fleet, loads, use_mock_llm=use_mock_llm)
    optimiser = run_fleet_optimizer(fleet, loads, compliance, top_k=top_k)

    return FleetWorkflowResult(
        fleet=fleet, available_loads=loads, sentry_log=sentry_log,
        compliance=compliance, analyst_log=analyst_log,
        optimiser=optimiser, error=None,
    )

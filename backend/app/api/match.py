"""POST /api/match/{truck_id} — run the agentic workflow + emit mock documents."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.agents.fleet_workflow import (
    MAX_FLEET_SIZE, analyst_fleet, run_fleet_match, sentry_fleet,
)
from app.agents.route_planner import plan_fleet_routes
from app.agents.workflow import run_match_workflow
from app.core.database import SessionLocal
from app.documents import build_cmr_document, build_sanitization_document

router = APIRouter(tags=["Potrivire & Planificare"])


def _resolve_truck_id(truck_id: int | None, plate: str | None) -> int:
    if truck_id is not None:
        return truck_id
    if plate is None:
        raise HTTPException(status_code=400, detail="Provide truck_id or plate")
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT id FROM trucks WHERE plate_number = :p"), {"p": plate}
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"truck plate {plate!r} not found")
    return int(row.id)


def _attach_documents(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("error"):
        return state

    decision = state.get("decision") or {}
    docs: dict[str, Any] = {
        "sanitization": build_sanitization_document(state),
    }
    if decision.get("chosen_load_id") is not None:
        docs["cmr"] = build_cmr_document(state)
    else:
        docs["cmr"] = {
            "document_type": "CMR",
            "status": "NOT_ISSUED",
            "reason": "No compliant load was matched; CMR not generated.",
        }

    return {**state, "documents": docs}


# NOTE: `/match/fleet` MUST be declared before `/match/{truck_id}` —
# otherwise FastAPI parses `fleet` as a truck_id path param and 422s.
@router.post(
    "/match/fleet",
    summary="Asignare multi-camion — top-K planuri alternative pentru intreaga flota",
)
def match_fleet_endpoint(
    top_k: int = Query(3, ge=1, le=5, description="Numar de planuri alternative (max 5)."),
    include_broker: bool = Query(
        True, description="Include incarcaturile de pe bursa spot (broker)."
    ),
    mock_llm: bool = Query(
        True,
        description=(
            "Sari peste Gemini la pasul de Analyst (implicit true pentru viteza). "
            "Seteaza false pentru a obtine verdicte cu citate din surse legale."
        ),
    ),
    fleet_size: int = Query(
        MAX_FLEET_SIZE, ge=1, le=MAX_FLEET_SIZE,
        description=f"Limiteaza flota la N camioane goale (implicit {MAX_FLEET_SIZE}).",
    ),
) -> dict:
    """Ruleaza Sentinela → Analist → CP-SAT multi-camion si returneaza
    top-K planuri de asignare alternative. Fiecare plan include defalcarea
    per camion si un bloc de statistici la nivel de flota (marja totala,
    raport deadhead, mix client/broker, grad de utilizare).
    """
    result = run_fleet_match(
        top_k=top_k,
        include_broker=include_broker,
        use_mock_llm=mock_llm,
        fleet_size=fleet_size,
    )
    if result["error"]:
        raise HTTPException(status_code=409, detail=result["error"])
    # The compliance dict has tuple keys, which JSON can't serialise — flatten.
    flat_compliance = [
        {"truck_id": t, "load_id": l, **v}
        for (t, l), v in result["compliance"].items()
    ]
    return {
        "fleet": result["fleet"],
        "available_loads": result["available_loads"],
        "sentry_log": result["sentry_log"],
        "analyst_log": result["analyst_log"],
        "optimiser": result["optimiser"],
        "compliance_matrix": flat_compliance,
    }


# NOTE: declared before /match/{truck_id} to avoid path-param collision.
@router.post(
    "/route/plan",
    summary="Plan zilnic de rute pentru flota de depou (cu lanturi multi-leg)",
)
def route_plan_endpoint(
    top_k: int = Query(3, ge=1, le=5),
    include_broker: bool = Query(True, description="Include incarcaturile de pe bursa spot."),
    enable_chains: bool = Query(True, description="Permite lanturi de 2 incarcaturi (backhaul chain)."),
    mock_llm: bool = Query(True, description="Sari peste Gemini la analiza de conformitate."),
    fleet_size: int = Query(MAX_FLEET_SIZE, ge=1, le=MAX_FLEET_SIZE),
) -> dict:
    """Plan complet de rute zilnice pentru un transportator cu depou.

    Ziua fiecarei dube este planificata ca IDLE / SINGLE (tur-retur) / CHAIN
    (doua incarcaturi). Returneaza top-K planuri alternative + defalcarea
    per duba + KPI-uri la nivel de flota.
    """
    sentry_out = sentry_fleet(include_broker=include_broker, fleet_size=fleet_size)
    if "error" in sentry_out:
        raise HTTPException(status_code=409, detail=sentry_out["error"])
    vans = sentry_out["fleet"]
    loads = sentry_out["available_loads"]
    compliance, analyst_log = analyst_fleet(vans, loads, use_mock_llm=mock_llm)
    optimiser = plan_fleet_routes(
        vans, loads, compliance, top_k=top_k, enable_chains=enable_chains,
    )
    flat_compliance = [
        {"truck_id": t, "load_id": l, **v}
        for (t, l), v in compliance.items()
    ]
    return {
        "depot": {
            "city": vans[0]["home_base_city"] if vans else None,
            "lat": vans[0]["lat"] if vans else None,
            "lon": vans[0]["lon"] if vans else None,
        },
        "fleet": vans,
        "available_loads": loads,
        "sentry_log": sentry_out["sentry_log"],
        "analyst_log": analyst_log,
        "optimiser": optimiser,
        "compliance_matrix": flat_compliance,
    }


@router.post(
    "/match/{truck_id}",
    summary="Ruleaza pipeline-ul Sentinela/Analist/Strategist pentru un camion",
)
def match_by_id(
    truck_id: int,
    mock_llm: bool = Query(
        False,
        description="Foloseste Analistul deterministic mock (fara apel Gemini).",
    ),
) -> dict:
    state = run_match_workflow(truck_id, use_mock_llm=mock_llm)
    if state.get("error") and not state.get("truck"):
        raise HTTPException(status_code=404, detail=state["error"])
    return _attach_documents(state)


@router.post(
    "/match",
    summary="Potrivire agentica dupa numar de inmatriculare (alternativa la /match/{id})",
)
def match_by_plate(
    plate: str = Query(..., description="Numar de inmatriculare, ex. B-202-CBO"),
    mock_llm: bool = Query(False),
) -> dict:
    truck_id = _resolve_truck_id(None, plate)
    state = run_match_workflow(truck_id, use_mock_llm=mock_llm)
    if state.get("error") and not state.get("truck"):
        raise HTTPException(status_code=404, detail=state["error"])
    return _attach_documents(state)

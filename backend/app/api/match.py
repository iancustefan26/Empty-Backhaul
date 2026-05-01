"""POST /api/match/{truck_id} — run the agentic workflow + emit mock documents."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.agents.workflow import run_match_workflow
from app.core.database import SessionLocal
from app.documents import build_cmr_document, build_sanitization_document

router = APIRouter(tags=["match"])


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


@router.post(
    "/match/{truck_id}",
    summary="Run the Sentry/Analyst/Strategist pipeline for a truck",
)
def match_by_id(
    truck_id: int,
    mock_llm: bool = Query(
        False,
        description="Use the deterministic mock Analyst (skips Anthropic API).",
    ),
) -> dict:
    state = run_match_workflow(truck_id, use_mock_llm=mock_llm)
    if state.get("error") and not state.get("truck"):
        raise HTTPException(status_code=404, detail=state["error"])
    return _attach_documents(state)


@router.post(
    "/match",
    summary="Run the agentic match by truck plate (alternative to /match/{id})",
)
def match_by_plate(
    plate: str = Query(..., description="Truck plate number, e.g. B-202-CBO"),
    mock_llm: bool = Query(False),
) -> dict:
    truck_id = _resolve_truck_id(None, plate)
    state = run_match_workflow(truck_id, use_mock_llm=mock_llm)
    if state.get("error") and not state.get("truck"):
        raise HTTPException(status_code=404, detail=state["error"])
    return _attach_documents(state)

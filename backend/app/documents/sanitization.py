"""Mock 'Declaratie de sanitizare a remorcii' (Romanian trailer sanitisation
declaration). Issued by the carrier/driver before loading temperature-
controlled or food-grade cargo. Backed by the trailer's most recent valid
wash certificate when one exists.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _declaration_number(truck_plate: str, now: datetime) -> str:
    return f"SAN-{truck_plate}-{now:%Y%m%d}-{now:%H%M}"


def _active_wash_certificate(truck_certs: list[dict]) -> dict | None:
    valid = [c for c in truck_certs if c.get("is_currently_valid")]
    if not valid:
        return None
    valid.sort(key=lambda c: c["valid_until"], reverse=True)
    return valid[0]


def build_sanitization_document(state: dict[str, Any]) -> dict[str, Any]:
    truck = state["truck"]
    decision = state["decision"]
    load = decision.get("chosen_load")

    now = datetime.now(timezone.utc)
    wash = _active_wash_certificate(truck["wash_certificates"])

    has_food_grade_next = bool(load and load["cargo_type"] in {
        "pharma", "dairy", "produce", "raw_meat", "raw_poultry",
        "ambient_dry", "frozen_vegetables", "frozen_fish",
    })

    if has_food_grade_next and not wash and truck["last_cargo"] not in {"clean", "pharma"}:
        sanitisation_basis = "Declaratie pe propria raspundere — fara certificat de spalare valabil"
    elif wash:
        sanitisation_basis = (
            f"Certificat de spalare {wash['wash_type']} numar {wash['certificate_number']}, "
            f"emis de {wash['issuing_facility'] or 'statie de spalare'}"
        )
    else:
        sanitisation_basis = "Trailer curat din ultima descarcare; nu se impune spalare oficiala"

    return {
        "document_type": "Declaratie sanitizare remorca",
        "declaration_number": _declaration_number(truck["plate_number"], now),
        "issued_at": now.isoformat(),
        "issued_at_human": now.strftime("%d.%m.%Y %H:%M UTC"),

        "vehicle": {
            "plate_number": truck["plate_number"],
            "carrier": truck["carrier_name"],
            "current_city": truck["current_city"],
            "temp_capability": truck["temp_capability"],
            "has_calibrated_pharma_logger": truck["has_pharma_logger"],
        },

        "previous_cargo": {
            "cargo_class": truck["last_cargo"],
            "carriage_completed": True,
        },

        "sanitisation_basis": sanitisation_basis,
        "wash_certificate": (
            {
                "certificate_number": wash["certificate_number"],
                "issued_at": wash["issued_at"],
                "valid_until": wash["valid_until"],
                "wash_type": wash["wash_type"],
                "issuing_facility": wash["issuing_facility"],
                "prior_cargo_decontaminated": wash["prior_cargo"],
                "currently_valid": wash["is_currently_valid"],
            } if wash else None
        ),

        "next_cargo_authorisation": (
            {
                "load_id": load["id"],
                "cargo_type": load["cargo_type"],
                "cargo_description": load["cargo_description"],
                "approved": True,
                "approval_basis": _approval_basis(state, load["id"]),
            } if load else {
                "approved": False,
                "approval_basis": ["No load was matched by the Strategist."],
            }
        ),

        "driver_acknowledgement": (
            "Subsemnatul, sofer, declar pe propria raspundere ca remorca este "
            "curata vizual, fara mirosuri anormale si fara reziduuri vizibile. "
            "Setpoint-ul de temperatura este reglat la intervalul cerut de "
            "incarcatura urmatoare. Imi asum responsabilitatea pentru orice "
            "neconformitate constatata la receptie."
        ),

        "notice": (
            "Acest document este o reprezentare mock generata automat de "
            "sistemul Agentic Cold Backhaul Optimizer. Pentru transporturi "
            "reale, foloseste formularul oficial ANSVSA cu semnatura olografa "
            "si stampila."
        ),
    }


def _approval_basis(state: dict[str, Any], load_id: int) -> list[str]:
    for v in state.get("compliance_results", []):
        if v["load_id"] == load_id:
            return v.get("cited_rule_ids", [])
    return []

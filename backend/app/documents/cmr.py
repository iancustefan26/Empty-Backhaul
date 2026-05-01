"""Mock CMR consignment note generator.

CMR (Convention relative au contrat de transport international de marchandises
par route) is the standard road-freight consignment note used across the EU,
including for Romanian domestic transports above a small threshold. We render
the boxes most relevant for a cold-chain backhaul demo; the full CMR has 24.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _consignment_number(truck_plate: str, load_id: int, now: datetime) -> str:
    return f"CMR-{now:%Y%m%d}-{now:%H%M}-{truck_plate}-L{load_id}"


def _active_wash_certificate(truck_certs: list[dict]) -> dict | None:
    valid = [c for c in truck_certs if c.get("is_currently_valid")]
    if not valid:
        return None
    valid.sort(key=lambda c: c["valid_until"], reverse=True)
    return valid[0]


def build_cmr_document(state: dict[str, Any]) -> dict[str, Any]:
    """Render a CMR consignment note for the chosen (truck, load) pair.

    Returns None-equivalent structure when there is no chosen load — the
    caller should normally guard on `state["decision"]["chosen_load_id"]`
    before calling.
    """
    truck = state["truck"]
    decision = state["decision"]
    load = decision["chosen_load"]
    if load is None:
        return {
            "document_type": "CMR",
            "status": "NOT_ISSUED",
            "reason": "No compliant load was matched; nothing to document.",
        }

    now = datetime.now(timezone.utc)
    wash = _active_wash_certificate(truck["wash_certificates"])

    return {
        "document_type": "CMR",
        "consignment_number": _consignment_number(truck["plate_number"], load["id"], now),
        "issued_at": now.isoformat(),
        "issued_at_human": now.strftime("%d.%m.%Y %H:%M UTC"),

        # CMR boxes — keys numbered to mirror the legal form layout.
        "boxes": {
            "01_sender": {
                "name": load["shipper_name"],
                "address": f"{load['pickup_city']}, Romania",
            },
            "02_consignee": {
                "name": "Destinatar (placeholder)",
                "address": f"{load['delivery_city']}, Romania",
            },
            "03_place_of_delivery": load["delivery_city"],
            "04_place_and_date_of_pickup": {
                "place": load["pickup_city"],
                "earliest": load["pickup_window_start"],
                "latest": load["pickup_window_end"],
            },
            "05_documents_attached": [
                "Sanitizare Trailer Declaration",
                wash["certificate_number"] if wash else None,
                "Logger calibration record" if load["requires_pharma_logger"] else None,
            ],
            "06_marks_and_numbers": load["cargo_description"],
            "09_nature_of_goods": load["cargo_type"],
            "11_gross_weight_kg": load["weight_kg"],
            "13_special_instructions": (
                f"Maintain temperature between {load['temp_min_celsius']} and "
                f"{load['temp_max_celsius']} C for the full transit. "
                + ("Calibrated continuous logger required." if load["requires_pharma_logger"] else "")
            ).strip(),
            "16_carrier": {
                "name": truck["carrier_name"] or "(carrier not declared)",
                "vehicle": truck["plate_number"],
                "vehicle_capability": truck["temp_capability"],
            },
            "20_payment_terms": {
                "agreed_price_eur": load["price_eur"],
                "to_be_paid_by": "consignee",
            },
            "21_established": {
                "place": load["pickup_city"],
                "date": now.date().isoformat(),
            },
        },

        # Compliance attachments cross-referenced by the Analyst.
        "compliance": {
            "wash_certificate_number": wash["certificate_number"] if wash else None,
            "wash_certificate_valid_until": wash["valid_until"] if wash else None,
            "pharma_logger_required": load["requires_pharma_logger"],
            "pharma_logger_present": truck["has_pharma_logger"],
            "cited_rule_ids": _cited_for_load(state, load["id"]),
        },

        "signatures": {
            "sender":   {"signed": False, "stamp_required": True},
            "carrier":  {"signed": False, "stamp_required": True},
            "consignee": {"signed": False, "stamp_required": True},
        },

        "notice": (
            "Acest document este o reprezentare mock generata automat de sistemul "
            "Agentic Cold Backhaul Optimizer si nu constituie un CMR legal. "
            "Inainte de transport, semneaza si stampileaza versiunea oficiala."
        ),
    }


def _cited_for_load(state: dict[str, Any], load_id: int) -> list[str]:
    for v in state.get("compliance_results", []):
        if v["load_id"] == load_id:
            return v.get("cited_rule_ids", [])
    return []

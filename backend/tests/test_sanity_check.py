"""Unit tests for the deterministic predicates and the sanity-merge layer.

These tests exercise `app.agents.sanity_check` in isolation — no DB, no
network, no LLM. They pin the rule semantics so the eval harness and the
mock evaluator can never silently drift.
"""
from __future__ import annotations

import pytest

from app.agents.sanity_check import (
    apply_sanity_layer,
    check_chemicals_quarantine,
    check_forbidden_prior_cargo,
    check_pharma_logger,
    check_temperature,
    has_valid_ansvsa_wash_for,
    hard_rules_verdict,
)
from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def make_truck(**overrides) -> TruckSnapshot:
    base = dict(
        id=1, plate_number="TEST-001", carrier_name="Test",
        temp_capability="chilled", last_cargo="dairy",
        has_pharma_logger=False, remaining_driving_hours=8.0,
        status="empty", current_city="Cluj", home_base_city="Bucuresti",
        lat=46.77, lon=23.6, wash_certificates=[],
    )
    base.update(overrides)
    return TruckSnapshot(**base)


def make_load(**overrides) -> LoadSnapshot:
    base = dict(
        id=10, shipper_name="Test Shipper", cargo_type="dairy",
        cargo_description="UHT milk",
        temp_min_celsius=2.0, temp_max_celsius=6.0,
        requires_pharma_logger=False, forbidden_prior_cargo=None,
        pickup_city="Cluj", delivery_city="Bucuresti",
        pickup_lat=46.77, pickup_lon=23.6,
        delivery_lat=44.43, delivery_lon=26.1,
        pickup_window_start="2026-05-06T08:00",
        pickup_window_end="2026-05-06T18:00",
        weight_kg=1000.0, price_eur=500.0, status="available",
    )
    base.update(overrides)
    return LoadSnapshot(**base)


def ansvsa_wash(prior_cargo: str = "raw_meat", valid: bool = True) -> dict:
    return {
        "certificate_number": f"ANSVSA-TEST-{prior_cargo}",
        "wash_type": "ansvsa_official",
        "prior_cargo": prior_cargo,
        "is_currently_valid": valid,
        "valid_until": "2026-05-31T08:00:00Z",
    }


# ---------------------------------------------------------------------------
# check_temperature
# ---------------------------------------------------------------------------

def test_temperature_chilled_carries_dairy():
    blk, _ = check_temperature(make_truck(temp_capability="chilled"), make_load(cargo_type="dairy"))
    assert blk is None


def test_temperature_pharma_2_8_carries_pharma():
    blk, _ = check_temperature(make_truck(temp_capability="pharma_2_8"), make_load(cargo_type="pharma"))
    assert blk is None


def test_temperature_chilled_blocks_frozen():
    blk, cited = check_temperature(make_truck(temp_capability="chilled"), make_load(cargo_type="frozen_vegetables"))
    assert blk is not None
    assert "temp.frozen-band" in cited


def test_temperature_ambient_blocks_pharma():
    blk, _ = check_temperature(make_truck(temp_capability="ambient"), make_load(cargo_type="pharma"))
    assert blk is not None


def test_temperature_frozen_carries_ambient_dry():
    """Frozen truck CAN carry ambient_dry — frozen capability is a superset."""
    blk, _ = check_temperature(make_truck(temp_capability="frozen"), make_load(cargo_type="ambient_dry"))
    assert blk is None


# ---------------------------------------------------------------------------
# check_pharma_logger
# ---------------------------------------------------------------------------

def test_pharma_logger_required_and_missing():
    blk, _ = check_pharma_logger(
        make_truck(has_pharma_logger=False),
        make_load(requires_pharma_logger=True),
    )
    assert blk is not None


def test_pharma_logger_present():
    blk, _ = check_pharma_logger(
        make_truck(has_pharma_logger=True),
        make_load(requires_pharma_logger=True),
    )
    assert blk is None


# ---------------------------------------------------------------------------
# check_chemicals_quarantine
# ---------------------------------------------------------------------------

def test_chemicals_blocks_food_grade():
    blk, _ = check_chemicals_quarantine(make_truck(last_cargo="chemicals"), make_load(cargo_type="dairy"))
    assert blk is not None


def test_chemicals_to_chemicals_ok():
    blk, _ = check_chemicals_quarantine(make_truck(last_cargo="chemicals"), make_load(cargo_type="chemicals"))
    assert blk is None


# ---------------------------------------------------------------------------
# check_forbidden_prior_cargo + ANSVSA wash override
# ---------------------------------------------------------------------------

def test_forbidden_list_direction_raw_meat_not_in_chemicals_list():
    """The QA-bug fix: load.forbidden=[chemicals], truck.last=raw_meat → COMPLIANT."""
    blk, warn, _ = check_forbidden_prior_cargo(
        make_truck(last_cargo="raw_meat"),
        make_load(cargo_type="raw_meat", forbidden_prior_cargo="chemicals"),
    )
    assert blk is None
    assert warn is None


def test_forbidden_list_blocks_when_truck_last_is_in_list():
    blk, warn, cited = check_forbidden_prior_cargo(
        make_truck(last_cargo="raw_meat"),
        make_load(cargo_type="dairy", forbidden_prior_cargo="raw_meat,raw_poultry,chemicals"),
    )
    assert blk is not None
    assert warn is None
    assert "load.forbidden-prior-cargo-list" in cited


def test_ansvsa_wash_overrides_forbidden_for_dairy():
    """The headline thesis demo: raw_meat → dairy with valid ANSVSA wash."""
    blk, warn, cited = check_forbidden_prior_cargo(
        make_truck(last_cargo="raw_meat", wash_certificates=[ansvsa_wash("raw_meat")]),
        make_load(cargo_type="dairy", forbidden_prior_cargo="raw_meat,raw_poultry,chemicals"),
    )
    assert blk is None
    assert warn is not None
    assert "ANSVSA wash certificate" in warn
    assert "haccp.raw-meat-to-non-meat-requires-ansvsa-wash" in cited
    assert "ansvsa.wash-certificate-validity" in cited


def test_expired_wash_does_not_override():
    blk, warn, _ = check_forbidden_prior_cargo(
        make_truck(last_cargo="raw_meat", wash_certificates=[ansvsa_wash("raw_meat", valid=False)]),
        make_load(cargo_type="dairy", forbidden_prior_cargo="raw_meat"),
    )
    assert blk is not None
    assert warn is None


def test_wash_for_wrong_prior_cargo_does_not_override():
    """Wash cert covers raw_poultry but truck's last cargo was raw_meat → no override."""
    blk, warn, _ = check_forbidden_prior_cargo(
        make_truck(last_cargo="raw_meat", wash_certificates=[ansvsa_wash("raw_poultry")]),
        make_load(cargo_type="dairy", forbidden_prior_cargo="raw_meat"),
    )
    assert blk is not None
    assert warn is None


def test_wash_does_not_override_for_pharma_load():
    """Wash override only applies to dairy/produce/ambient_dry, NOT pharma."""
    blk, warn, _ = check_forbidden_prior_cargo(
        make_truck(last_cargo="raw_meat", wash_certificates=[ansvsa_wash("raw_meat")]),
        make_load(cargo_type="pharma", forbidden_prior_cargo="raw_meat"),
    )
    assert blk is not None
    assert warn is None


def test_has_valid_ansvsa_wash_for_helper():
    truck = make_truck(wash_certificates=[ansvsa_wash("raw_meat"), ansvsa_wash("raw_poultry", valid=False)])
    assert has_valid_ansvsa_wash_for(truck, "raw_meat") is not None
    assert has_valid_ansvsa_wash_for(truck, "raw_poultry") is None  # expired
    assert has_valid_ansvsa_wash_for(truck, "chemicals") is None    # not present


# ---------------------------------------------------------------------------
# hard_rules_verdict aggregate
# ---------------------------------------------------------------------------

def test_hard_rules_compliant_path():
    hv = hard_rules_verdict(
        make_truck(temp_capability="multi_temp", last_cargo="clean"),
        make_load(cargo_type="dairy"),
    )
    assert hv["is_compliant"]
    assert hv["blockers"] == []


def test_hard_rules_multi_blocker():
    hv = hard_rules_verdict(
        make_truck(temp_capability="ambient", last_cargo="chemicals", has_pharma_logger=False),
        make_load(cargo_type="pharma", requires_pharma_logger=True),
    )
    assert not hv["is_compliant"]
    assert len(hv["blockers"]) >= 2  # temp + chemicals + logger


# ---------------------------------------------------------------------------
# apply_sanity_layer merge logic
# ---------------------------------------------------------------------------

def make_llm_verdict(load_id=10, **overrides) -> ComplianceVerdict:
    base = dict(
        load_id=load_id, is_compliant=True, confidence=0.9,
        blockers=[], warnings=[], reasoning="LLM-said.",
        cited_rule_ids=[], cited_excerpts=[], sanity_overrides=[],
    )
    base.update(overrides)
    return ComplianceVerdict(**base)


def test_sanity_layer_passes_through_when_verdicts_agree():
    truck = make_truck(temp_capability="multi_temp", last_cargo="clean")
    load = make_load(cargo_type="dairy")
    hard = hard_rules_verdict(truck, load)  # compliant
    llm = make_llm_verdict(is_compliant=True)
    out, overrides = apply_sanity_layer(llm, hard, truck, load)
    assert out["is_compliant"] is True
    assert out["sanity_overrides"] == []
    assert overrides == []


def test_sanity_layer_corrects_false_block_via_wash_override():
    truck = make_truck(last_cargo="raw_meat", wash_certificates=[ansvsa_wash("raw_meat")])
    load = make_load(cargo_type="dairy", forbidden_prior_cargo="raw_meat,raw_poultry,chemicals")
    hard = hard_rules_verdict(truck, load)  # compliant via wash override
    llm = make_llm_verdict(
        is_compliant=False,
        blockers=["forbidden prior cargo applies"],
        cited_rule_ids=["load.forbidden-prior-cargo-list"],
    )
    out, overrides = apply_sanity_layer(llm, hard, truck, load)
    assert out["is_compliant"] is True
    assert out["blockers"] == []
    assert "wash-override-missed" in overrides
    assert any("ANSVSA" in w for w in out["warnings"])


def test_sanity_layer_corrects_false_pass_chemicals():
    truck = make_truck(temp_capability="multi_temp", last_cargo="chemicals")
    load = make_load(cargo_type="dairy")
    hard = hard_rules_verdict(truck, load)  # blocked by chemicals quarantine
    llm = make_llm_verdict(is_compliant=True)
    out, overrides = apply_sanity_layer(llm, hard, truck, load)
    assert out["is_compliant"] is False
    assert "chemicals-quarantine-missed" in overrides
    assert any("chemicals" in b.lower() for b in out["blockers"])


def test_sanity_layer_preserves_llm_reasoning_and_excerpts():
    truck = make_truck(last_cargo="raw_meat", wash_certificates=[ansvsa_wash("raw_meat")])
    load = make_load(cargo_type="dairy", forbidden_prior_cargo="raw_meat")
    hard = hard_rules_verdict(truck, load)
    llm = make_llm_verdict(
        is_compliant=False,
        blockers=["fake LLM blocker"],
        reasoning="The LLM said something wrong.",
        cited_excerpts=[{"source_id": "ansvsa.test", "citation": "x", "language": "ro", "snippet": "test", "distance": 0.1}],
    )
    out, _ = apply_sanity_layer(llm, hard, truck, load)
    assert out["reasoning"] == "The LLM said something wrong."
    assert len(out["cited_excerpts"]) == 1
    assert out["cited_excerpts"][0]["source_id"] == "ansvsa.test"


def test_sanity_layer_caps_confidence_when_overriding():
    truck = make_truck(temp_capability="multi_temp", last_cargo="chemicals")
    load = make_load(cargo_type="dairy")
    hard = hard_rules_verdict(truck, load)
    llm = make_llm_verdict(is_compliant=True, confidence=1.0)
    out, _ = apply_sanity_layer(llm, hard, truck, load)
    assert out["confidence"] <= 0.99

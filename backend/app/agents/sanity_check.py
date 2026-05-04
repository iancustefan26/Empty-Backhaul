"""Deterministic post-LLM sanity layer for Analyst verdicts.

The LLM is great at warnings, reasoning prose, and picking citations from the
primary corpus. It is not always reliable on the *deterministic* hard rules
(temperature capability, pharma logger, chemicals quarantine, forbidden prior
cargo with ANSVSA wash override). For those rules we have a single source of
truth — the same logic that powers `_evaluate_mock` — and we re-run it after
every LLM call. If the LLM verdict disagrees with the hard rules, the hard
rules win and the corrected verdict carries a `sanity_overrides` list naming
which rule(s) were enforced.

This module exposes:

  - Pure predicates per rule, returning `(blocker, warning, cited_rule_ids)`
    so they can be unit-tested in isolation and reused by the mock evaluator.
  - `hard_rules_verdict(truck, load)` — runs all predicates, returns a
    HardVerdict dict that mirrors the relevant ComplianceVerdict fields.
  - `apply_sanity_layer(llm_verdict, hard, ...)` — merges the LLM verdict
    with the hard verdict per the rules in the plan's "merge semantics" table.

Override-key vocabulary (stable strings used in `sanity_overrides`):

  - `temp-capability-mismatch`         hard says blocked, LLM said compliant
  - `temp-capability-false-block`      hard says compliant, LLM blocked
  - `pharma-logger-missing`            hard says blocked (logger required), LLM said compliant
  - `chemicals-quarantine-missed`      hard says blocked (chemicals→food), LLM said compliant
  - `forbidden-prior-cargo-missed`     hard says blocked, LLM said compliant
  - `forbidden-prior-cargo-false-block` hard says compliant (or wash override), LLM blocked
  - `wash-override-missed`             hard says compliant via wash, LLM blocked
"""
from __future__ import annotations

from typing import TypedDict

from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot

# ---------------------------------------------------------------------------
# Rule data (mirrored from analyst._evaluate_mock so this module is the
# single source of truth; analyst._evaluate_mock will be refactored to
# import from here).
# ---------------------------------------------------------------------------

TEMP_CAPABILITY_FOR_CARGO: dict[str, set[str]] = {
    "frozen_vegetables": {"frozen", "multi_temp"},
    "frozen_fish":       {"frozen", "multi_temp"},
    "pharma":            {"pharma_2_8", "multi_temp"},
    "dairy":             {"chilled", "multi_temp", "pharma_2_8"},
    "produce":           {"chilled", "multi_temp", "pharma_2_8"},
    "raw_meat":          {"chilled", "multi_temp"},
    "raw_poultry":       {"chilled", "multi_temp"},
    "ambient_dry":       {"chilled", "multi_temp", "pharma_2_8", "frozen", "ambient"},
    "chemicals":         {"chilled", "multi_temp", "ambient"},
}

FOOD_GRADE_CARGO: set[str] = {
    "pharma", "dairy", "produce", "raw_meat", "raw_poultry",
    "ambient_dry", "frozen_vegetables", "frozen_fish",
}

WASH_OVERRIDE_LOAD_TYPES: set[str] = {"dairy", "produce", "ambient_dry"}
WASH_OVERRIDE_PRIOR_CARGOES: set[str] = {"raw_meat", "raw_poultry"}


class HardVerdict(TypedDict):
    is_compliant: bool
    blockers: list[str]
    warnings: list[str]
    cited_rule_ids: list[str]


# ---------------------------------------------------------------------------
# Pure predicates
# ---------------------------------------------------------------------------

def check_temperature(truck: TruckSnapshot, load: LoadSnapshot) -> tuple[str | None, list[str]]:
    """Return (blocker_message_or_None, cited_rule_ids)."""
    allowed = TEMP_CAPABILITY_FOR_CARGO.get(load["cargo_type"], set())
    if not allowed or truck["temp_capability"] in allowed:
        return None, []
    cited = ["temp.frozen-band" if load["cargo_type"].startswith("frozen") else "temp.chilled-band",
             "temp.ambient-restrictions"]
    msg = (f"temp_capability={truck['temp_capability']} cannot carry {load['cargo_type']} "
           f"(needs one of {sorted(allowed)})")
    return msg, cited


def check_pharma_logger(truck: TruckSnapshot, load: LoadSnapshot) -> tuple[str | None, list[str]]:
    if load["requires_pharma_logger"] and not truck["has_pharma_logger"]:
        return ("pharma load requires a calibrated logger; truck has none",
                ["gdp.pharma-temperature-and-logger"])
    return None, []


def check_chemicals_quarantine(truck: TruckSnapshot, load: LoadSnapshot) -> tuple[str | None, list[str]]:
    if truck["last_cargo"] == "chemicals" and load["cargo_type"] in FOOD_GRADE_CARGO:
        return ("truck's last cargo was chemicals; food-grade reuse blocked irrespective of standard wash",
                ["haccp.chemicals-quarantine"])
    return None, []


def has_valid_ansvsa_wash_for(truck: TruckSnapshot, prior_cargo: str) -> dict | None:
    """Return the matching valid ANSVSA wash certificate dict if one exists."""
    for w in truck.get("wash_certificates") or []:
        if (w.get("is_currently_valid")
                and w.get("wash_type") == "ansvsa_official"
                and w.get("prior_cargo") == prior_cargo):
            return w
    return None


def check_forbidden_prior_cargo(
    truck: TruckSnapshot, load: LoadSnapshot,
) -> tuple[str | None, str | None, list[str]]:
    """Return (blocker_or_None, warning_or_None, cited_rule_ids).

    Implements the wash-override: when truck.last_cargo is on the forbidden
    list AND the truck has a valid ANSVSA wash certificate AND the load is
    one of the override-eligible types, the blocker becomes a warning.
    """
    raw = load.get("forbidden_prior_cargo")
    if not raw:
        return None, None, []
    forbidden = {c.strip() for c in raw.split(",") if c.strip()}
    if truck["last_cargo"] not in forbidden:
        return None, None, []

    # Forbidden — check for ANSVSA wash override.
    wash = has_valid_ansvsa_wash_for(truck, truck["last_cargo"])
    can_override = (
        wash is not None
        and truck["last_cargo"] in WASH_OVERRIDE_PRIOR_CARGOES
        and load["cargo_type"] in WASH_OVERRIDE_LOAD_TYPES
    )
    if can_override:
        cert_no = wash.get("certificate_number", "<unknown>")
        warning = (f"prior cargo {truck['last_cargo']} normally forbidden, "
                   f"unblocked by valid ANSVSA wash certificate {cert_no}")
        cited = ["haccp.raw-meat-to-non-meat-requires-ansvsa-wash",
                 "ansvsa.wash-certificate-validity"]
        return None, warning, cited

    blocker = (f"truck's last_cargo={truck['last_cargo']} is on the load's forbidden list "
               f"({raw})")
    cited = ["load.forbidden-prior-cargo-list"]
    if truck["last_cargo"] in WASH_OVERRIDE_PRIOR_CARGOES:
        cited.append("haccp.raw-meat-to-non-meat-requires-ansvsa-wash")
    return blocker, None, cited


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def hard_rules_verdict(truck: TruckSnapshot, load: LoadSnapshot) -> HardVerdict:
    blockers: list[str] = []
    warnings: list[str] = []
    cited: list[str] = []

    for blocker_msg, c in (
        check_temperature(truck, load),
        check_pharma_logger(truck, load),
        check_chemicals_quarantine(truck, load),
    ):
        if blocker_msg:
            blockers.append(blocker_msg)
        cited.extend(c)

    fp_blocker, fp_warning, fp_cited = check_forbidden_prior_cargo(truck, load)
    if fp_blocker:
        blockers.append(fp_blocker)
    if fp_warning:
        warnings.append(fp_warning)
    cited.extend(fp_cited)

    # Pharma cleanliness citation when load is pharma and prior is not pharma/clean
    # (covered transitively by forbidden_prior_cargo for pharma loads, but cite the rule).
    if load["cargo_type"] == "pharma" and truck["last_cargo"] not in {"pharma", "clean"}:
        cited.append("gdp.pharma-cleanliness")

    return HardVerdict(
        is_compliant=not blockers,
        blockers=blockers,
        warnings=warnings,
        cited_rule_ids=sorted(set(cited)),
    )


# ---------------------------------------------------------------------------
# Merge LLM verdict with hard verdict
# ---------------------------------------------------------------------------

def _classify_overrides(
    truck: TruckSnapshot,
    load: LoadSnapshot,
    llm: ComplianceVerdict,
    hard: HardVerdict,
) -> list[str]:
    """Tag the override(s) with stable rule keys so the UI can explain."""
    tags: list[str] = []
    if llm["is_compliant"] == hard["is_compliant"]:
        return tags

    # The LLM and hard verdicts disagree. Diagnose the cause by re-running
    # individual predicates, so the tag is precise.
    temp_blk, _ = check_temperature(truck, load)
    logger_blk, _ = check_pharma_logger(truck, load)
    chem_blk, _ = check_chemicals_quarantine(truck, load)
    fp_blk, fp_warn, _ = check_forbidden_prior_cargo(truck, load)

    if hard["is_compliant"] and not llm["is_compliant"]:
        # LLM falsely blocked. Identify which rule the LLM mis-applied.
        if fp_warn is not None:
            tags.append("wash-override-missed")
        elif fp_blk is None and any("forbidden" in b.lower() for b in llm["blockers"]):
            tags.append("forbidden-prior-cargo-false-block")
        elif temp_blk is None and any("temp" in b.lower() or "capability" in b.lower() for b in llm["blockers"]):
            tags.append("temp-capability-false-block")
        else:
            tags.append("llm-false-block")
    else:
        # LLM falsely passed. Identify which hard rule the LLM missed.
        if chem_blk is not None:
            tags.append("chemicals-quarantine-missed")
        if logger_blk is not None:
            tags.append("pharma-logger-missing")
        if temp_blk is not None:
            tags.append("temp-capability-mismatch")
        if fp_blk is not None:
            tags.append("forbidden-prior-cargo-missed")
        if not tags:
            tags.append("llm-false-pass")
    return tags


def apply_sanity_layer(
    llm: ComplianceVerdict,
    hard: HardVerdict,
    truck: TruckSnapshot,
    load: LoadSnapshot,
) -> tuple[ComplianceVerdict, list[str]]:
    """Merge an LLM verdict with the deterministic hard-rules verdict.

    Returns (corrected_verdict, sanity_overrides). When the two verdicts
    agree, sanity_overrides is empty and the LLM verdict is returned with
    its `sanity_overrides` field set to []. When they disagree, hard rules
    take precedence on `is_compliant` and `blockers`; warnings union; the
    LLM keeps `confidence` (capped at 0.99 to flag uncertainty), `reasoning`,
    and `cited_excerpts`.
    """
    overrides = _classify_overrides(truck, load, llm, hard)

    if not overrides:
        out = ComplianceVerdict(
            **{k: v for k, v in llm.items() if k != "sanity_overrides"},  # type: ignore[arg-type]
            sanity_overrides=[],
        )
        return out, []

    # Disagreement → hard wins on is_compliant + blockers; warnings union;
    # cited_rule_ids union; LLM keeps reasoning + cited_excerpts; confidence
    # capped to flag the auto-correction.
    merged_warnings = list(dict.fromkeys([*llm["warnings"], *hard["warnings"]]))
    merged_cited_ids = sorted({*llm["cited_rule_ids"], *hard["cited_rule_ids"]})
    confidence = min(float(llm.get("confidence", 0.5)), 0.99)

    corrected = ComplianceVerdict(
        load_id=llm["load_id"],
        is_compliant=hard["is_compliant"],
        confidence=confidence,
        blockers=list(hard["blockers"]),
        warnings=merged_warnings,
        reasoning=llm["reasoning"],
        cited_rule_ids=merged_cited_ids,
        cited_excerpts=llm.get("cited_excerpts", []),
        sanity_overrides=overrides,
    )
    return corrected, overrides

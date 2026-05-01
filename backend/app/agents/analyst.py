"""Agent 2 — Analyst.

For each (truck, load) candidate pair: pulls the most relevant compliance
rules from Chroma, asks Claude to render a JSON verdict, and falls back to
a deterministic rule-evaluator when no API key is configured or
`use_mock_llm=True` is set on the workflow state.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from app.agents.state import ComplianceVerdict, LoadSnapshot, TruckSnapshot, WorkflowState
from app.rag.ingest import query_rules


# ------------------------- prompt building -------------------------

_SYSTEM_PROMPT = """You are the Compliance Analyst inside a multi-agent
cold-chain backhaul optimisation system for Romania. Given a truck profile,
a candidate load profile, and a set of compliance rules retrieved from a
vector database, you decide whether the truck is permitted to carry that
load under Romanian (ANSVSA), EU (HACCP, GDP, EU 561/2006) and
customer-specific constraints.

You always reason step-by-step internally but you only output a single JSON
object that matches this schema EXACTLY:

{
  "is_compliant": boolean,
  "confidence":   number,     // 0.0 - 1.0
  "blockers":     string[],   // hard violations (empty list if none)
  "warnings":     string[],   // soft issues worth flagging (empty list if none)
  "reasoning":    string,     // 2-4 plain-English sentences
  "cited_rule_ids": string[]  // ids of rules from the retrieved set you relied on
}

No prose outside the JSON. No markdown fences. No keys other than the six above.
"""


def _format_rules(rules: list[dict]) -> str:
    out = []
    for r in rules:
        meta = r["metadata"]
        out.append(
            f"- id: {r['id']}\n"
            f"  title: {meta['title']}\n"
            f"  regulation: {meta['regulation']}  severity: {meta['severity']}\n"
            f"  text: {r['text']}"
        )
    return "\n".join(out)


def _format_wash_certs(certs: list[dict]) -> str:
    if not certs:
        return "  (none on file)"
    lines = []
    for c in certs:
        valid = "VALID" if c["is_currently_valid"] else "EXPIRED/NOT-YET-EFFECTIVE"
        lines.append(
            f"  - {c['certificate_number']} ({c['wash_type']}, after {c['prior_cargo']!r}) "
            f"-> {valid} until {c['valid_until']}"
        )
    return "\n".join(lines)


def _build_query(truck: TruckSnapshot, load: LoadSnapshot) -> str:
    has_valid_wash = any(w["is_currently_valid"] for w in truck["wash_certificates"])
    return (
        f"Truck capability={truck['temp_capability']}, last cargo={truck['last_cargo']}, "
        f"pharma logger={truck['has_pharma_logger']}, valid wash cert={has_valid_wash}; "
        f"candidate load: {load['cargo_type']} at "
        f"{load['temp_min_celsius']} to {load['temp_max_celsius']} C from "
        f"{load['pickup_city']} to {load['delivery_city']}; "
        f"forbidden prior cargo: {load['forbidden_prior_cargo'] or 'none'}"
    )


def _build_user_message(truck: TruckSnapshot, load: LoadSnapshot, rules: list[dict]) -> str:
    return f"""TRUCK
Plate: {truck['plate_number']} ({truck['carrier_name'] or 'unknown carrier'})
Capability: {truck['temp_capability']}
Last cargo: {truck['last_cargo']}
Calibrated pharma logger: {truck['has_pharma_logger']}
Remaining driving hours: {truck['remaining_driving_hours']}
Currently in: {truck['current_city']} (returning to {truck['home_base_city']})
Wash certificates currently held:
{_format_wash_certs(truck['wash_certificates'])}

CANDIDATE LOAD (id={load['id']})
Cargo type: {load['cargo_type']}
Description: {load['cargo_description']}
Required temperature window: {load['temp_min_celsius']} to {load['temp_max_celsius']} C
Requires pharma logger: {load['requires_pharma_logger']}
Load-declared forbidden prior cargo: {load['forbidden_prior_cargo'] or 'none'}
Pickup -> delivery: {load['pickup_city']} -> {load['delivery_city']}
Pickup window: {load['pickup_window_start']} to {load['pickup_window_end']}

RELEVANT COMPLIANCE RULES (top {len(rules)} by similarity)
{_format_rules(rules)}

Decide whether this truck is permitted to take this load. Cite by id every
rule you relied on. Return JSON only.
"""


# ------------------------- JSON parsing -------------------------

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_verdict(raw: str, load_id: int) -> ComplianceVerdict:
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences if Claude added them
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise
        data = json.loads(m.group(0))

    return ComplianceVerdict(
        load_id=load_id,
        is_compliant=bool(data["is_compliant"]),
        confidence=float(data.get("confidence", 0.5)),
        blockers=list(data.get("blockers", [])),
        warnings=list(data.get("warnings", [])),
        reasoning=str(data.get("reasoning", "")),
        cited_rule_ids=list(data.get("cited_rule_ids", [])),
    )


# ------------------------- Claude call -------------------------

def _call_claude(system: str, user: str) -> str:
    from anthropic import Anthropic  # imported lazily so mock-only runs don't need it
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    client = Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


# ------------------------- deterministic mock evaluator -------------------------

_TEMP_CAPABILITY_FOR_CARGO: dict[str, set[str]] = {
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

_FOOD_GRADE_CARGO = {
    "pharma", "dairy", "produce", "raw_meat", "raw_poultry",
    "ambient_dry", "frozen_vegetables", "frozen_fish",
}


def _evaluate_mock(truck: TruckSnapshot, load: LoadSnapshot) -> ComplianceVerdict:
    blockers: list[str] = []
    warnings: list[str] = []
    cited: set[str] = set()

    # 1. temperature capability
    allowed = _TEMP_CAPABILITY_FOR_CARGO.get(load["cargo_type"], set())
    if allowed and truck["temp_capability"] not in allowed:
        blockers.append(
            f"temp_capability={truck['temp_capability']} cannot carry {load['cargo_type']} "
            f"(needs one of {sorted(allowed)})"
        )
        cited.add("temp.frozen-band" if load["cargo_type"].startswith("frozen") else "temp.chilled-band")
        cited.add("temp.ambient-restrictions")

    # 2. pharma logger
    if load["requires_pharma_logger"] and not truck["has_pharma_logger"]:
        blockers.append("pharma load requires a calibrated logger; truck has none")
        cited.add("gdp.pharma-temperature-and-logger")

    # 3. chemicals quarantine — never compatible with food-grade
    if truck["last_cargo"] == "chemicals" and load["cargo_type"] in _FOOD_GRADE_CARGO:
        blockers.append(
            "truck's last cargo was chemicals; food-grade reuse blocked irrespective of standard wash"
        )
        cited.add("haccp.chemicals-quarantine")

    # 4. forbidden_prior_cargo on the load
    if load["forbidden_prior_cargo"]:
        forbidden = {c.strip() for c in load["forbidden_prior_cargo"].split(",")}
        if truck["last_cargo"] in forbidden:
            # ANSVSA wash override only for raw_meat/raw_poultry -> dairy/produce/ambient_dry
            override = (
                truck["last_cargo"] in {"raw_meat", "raw_poultry"}
                and load["cargo_type"] in {"dairy", "produce", "ambient_dry"}
                and any(
                    w["is_currently_valid"] and w["wash_type"] == "ansvsa_official"
                    and w["prior_cargo"] == truck["last_cargo"]
                    for w in truck["wash_certificates"]
                )
            )
            if override:
                warnings.append(
                    f"prior cargo {truck['last_cargo']} normally forbidden, unblocked by valid "
                    f"ANSVSA wash certificate"
                )
                cited.add("haccp.raw-meat-to-non-meat-requires-ansvsa-wash")
                cited.add("ansvsa.wash-certificate-validity")
            else:
                blockers.append(
                    f"truck's last_cargo={truck['last_cargo']} is on the load's forbidden list "
                    f"({load['forbidden_prior_cargo']})"
                )
                cited.add("load.forbidden-prior-cargo-list")
                if truck["last_cargo"] in {"raw_meat", "raw_poultry"}:
                    cited.add("haccp.raw-meat-to-non-meat-requires-ansvsa-wash")

    # 5. pharma cleanliness
    if load["cargo_type"] == "pharma" and truck["last_cargo"] not in {"pharma", "clean"}:
        # pharma cleanliness already covered by forbidden_prior_cargo on pharma loads, but
        # cite the rule if it triggered
        cited.add("gdp.pharma-cleanliness")

    is_compliant = not blockers
    confidence = 0.95 if is_compliant else 0.92  # mock is deterministic
    if is_compliant and not cited:
        cited.add("temp.chilled-band")  # default citation if everything's trivially clean

    reasoning = (
        f"Mock-LLM analyst: {'COMPLIANT' if is_compliant else 'NOT COMPLIANT'} for truck "
        f"{truck['plate_number']} (last={truck['last_cargo']}, cap={truck['temp_capability']}) "
        f"vs load #{load['id']} {load['cargo_type']} {load['pickup_city']}->{load['delivery_city']}. "
        + (f"Blockers: {'; '.join(blockers)}." if blockers else "All capability, logger, and "
           "prior-cargo rules satisfied.")
    )

    return ComplianceVerdict(
        load_id=load["id"],
        is_compliant=is_compliant,
        confidence=confidence,
        blockers=blockers,
        warnings=warnings,
        reasoning=reasoning,
        cited_rule_ids=sorted(cited),
    )


# ------------------------- orchestrator -------------------------

def _should_use_mock(state: WorkflowState) -> bool:
    if state.get("use_mock_llm"):
        return True
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return True
    return False


def analyst_node(state: WorkflowState) -> dict:
    truck = state["truck"]
    loads = state.get("available_loads", [])
    use_mock = _should_use_mock(state)

    started = time.perf_counter()
    verdicts: list[ComplianceVerdict] = []
    rag_hits = 0
    llm_calls = 0
    parse_errors = 0

    for load in loads:
        rules = query_rules(_build_query(truck, load), k=5)
        rag_hits += len(rules)

        if use_mock:
            verdicts.append(_evaluate_mock(truck, load))
            continue

        try:
            raw = _call_claude(_SYSTEM_PROMPT, _build_user_message(truck, load, rules))
            llm_calls += 1
            verdicts.append(_parse_verdict(raw, load["id"]))
        except Exception as exc:
            parse_errors += 1
            verdicts.append(ComplianceVerdict(
                load_id=load["id"],
                is_compliant=False,
                confidence=0.0,
                blockers=[f"analyst failed: {type(exc).__name__}: {exc}"],
                warnings=[],
                reasoning=f"Claude call or JSON parse failed; treating as non-compliant.",
                cited_rule_ids=[],
            ))

    analyst_log: dict[str, Any] = {
        "mode": "mock" if use_mock else "claude",
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5") if not use_mock else None,
        "evaluated_loads": len(verdicts),
        "compliant_count": sum(1 for v in verdicts if v["is_compliant"]),
        "rag_hits": rag_hits,
        "llm_calls": llm_calls,
        "parse_errors": parse_errors,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    return {"compliance_results": verdicts, "analyst_log": analyst_log}

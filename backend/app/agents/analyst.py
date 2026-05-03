"""Agent 2 — Analyst.

For each (truck, load) candidate pair: pulls the most relevant compliance
rules from Chroma, asks an LLM (Gemini, Claude, ...) to render a JSON
verdict, and falls back to a deterministic rule-evaluator when no API key
is configured or `use_mock_llm=True` is set on the workflow state.

The concrete LLM is selected by `app.agents.llm_provider.get_provider()`
(driven by the `LLM_PROVIDER` env var; `auto` prefers Gemini, then
Anthropic, then the deterministic mock).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from app.agents.llm_provider import LLMProvider, MockProvider, get_provider
from app.agents.prompt_examples import WORKED_EXAMPLES
from app.agents.state import (
    ComplianceVerdict,
    ExcerptCitation,
    LoadSnapshot,
    TruckSnapshot,
    WorkflowState,
)
from app.rag.ingest import query_corpus, query_rules

EXCERPT_CHAR_BUDGET = 600   # max chars per source excerpt fed to the LLM
SNIPPET_CHAR_BUDGET = 240   # max chars per quoted snippet returned to the UI


# ------------------------- prompt building -------------------------

_SYSTEM_PROMPT = f"""You are the Compliance Analyst inside a multi-agent
cold-chain backhaul optimisation system for Romania. Given a truck profile,
a candidate load profile, a set of curated compliance rules, and verbatim
excerpts from primary legal sources (EU regulations and Romanian ANSVSA
orders), you decide whether the truck is permitted to carry that load under
Romanian (ANSVSA), EU (HACCP, GDP, EU 561/2006) and customer-specific
constraints.

You always reason step-by-step internally but you only output a single JSON
object that matches this schema EXACTLY:

{{
  "is_compliant": boolean,
  "confidence":   number,         // 0.0 - 1.0
  "blockers":     string[],       // hard violations (empty list if none)
  "warnings":     string[],       // soft issues worth flagging (empty list if none)
  "reasoning":    string,         // 2-4 plain-English sentences
  "cited_rule_ids": string[],     // ids of rules from the curated set you relied on
  "citations":    Citation[]      // 0-3 verbatim quotes from the source excerpts
}}

Citation = {{
  "source_id": string,            // must match one of the offered source_id values
  "snippet":   string             // verbatim fragment from the excerpt text (10-300 chars)
}}

CRITICAL HARD RULES — apply these mechanically, do not "reason around" them:

1. forbidden_prior_cargo (DIRECTION matters):
   This is the load's requirement about the TRUCK's PREVIOUS cargo. The
   blocker fires IF AND ONLY IF `truck.last_cargo` is one of the
   comma-separated values in the load's forbidden_prior_cargo list.
   The load's OWN cargo type is irrelevant to this check.
   Example: load.forbidden_prior_cargo="chemicals" + truck.last_cargo="raw_meat"
            → NOT a blocker (raw_meat is not in {{chemicals}}).

2. ANSVSA wash-certificate override:
   If the truck holds a wash certificate where ALL of:
     - is_currently_valid = True
     - wash_type = "ansvsa_official"
     - prior_cargo == truck.last_cargo
   THEN the truck's last_cargo NO LONGER triggers a forbidden_prior_cargo
   blocker for loads whose cargo_type is in {{dairy, produce, ambient_dry}}.
   Emit a warning ("prior cargo X normally forbidden, unblocked by valid
   ANSVSA wash certificate <number>") instead of a blocker.
   Cite haccp.raw-meat-to-non-meat-requires-ansvsa-wash AND
   ansvsa.wash-certificate-validity.

3. Chemicals quarantine:
   If truck.last_cargo == "chemicals" AND load.cargo_type is any food-grade
   cargo (pharma, dairy, produce, raw_meat, raw_poultry, ambient_dry,
   frozen_vegetables, frozen_fish), the load is BLOCKED regardless of any
   wash certificate. Cite haccp.chemicals-quarantine.

4. Temperature capability matching:
   - frozen / frozen_fish loads need truck capability ∈ {{frozen, multi_temp}}
   - chilled-range loads (dairy, produce, raw_meat, raw_poultry) need ∈ {{chilled, multi_temp}}
   - pharma 2-8°C needs ∈ {{pharma_2_8, multi_temp}} AND has_pharma_logger=True
   - ambient_dry/chemicals loads can be carried by any temp-controlled or ambient truck

The `citations` list grounds your verdict in primary law. ALWAYS include
at least one citation when the excerpts contain anything topically related
to the truck/load/blocker — even a single relevant sentence about hygiene,
transport, sanitation, food safety, pharma cold-chain, or wash certificates
is enough. Pick the closest excerpt by topic, copy a verbatim fragment of
its text into `snippet` (10 to 300 characters, no paraphrasing). Romanian
sources stay in Romanian. Only return [] if every offered excerpt is
completely off-topic for this case.

No prose outside the JSON. No markdown fences. No keys other than the seven above.

WORKED EXAMPLES (study these patterns; the third one tests rule 1 above and
the second one tests rule 2 — these are the exact failure modes the system
must avoid):

{WORKED_EXAMPLES}
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


def _format_excerpts(excerpts: list[dict]) -> str:
    if not excerpts:
        return "  (no relevant excerpts retrieved)"
    out = []
    for e in excerpts:
        meta = e["metadata"]
        body = e["text"][:EXCERPT_CHAR_BUDGET]
        if len(e["text"]) > EXCERPT_CHAR_BUDGET:
            body += "…"
        article = f"  Article: {meta['article']}\n" if meta.get("article") else ""
        out.append(
            f"- source_id: {meta['source_id']}\n"
            f"  citation: {meta['citation']}  ({meta['language']})\n"
            f"{article}"
            f"  text: {body}"
        )
    return "\n".join(out)


def _build_user_message(
    truck: TruckSnapshot,
    load: LoadSnapshot,
    rules: list[dict],
    excerpts: list[dict],
) -> str:
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

RELEVANT CURATED COMPLIANCE RULES (top {len(rules)} by similarity)
{_format_rules(rules)}

PRIMARY-SOURCE EXCERPTS (top {len(excerpts)} by similarity)
{_format_excerpts(excerpts)}

Decide whether this truck is permitted to take this load. Cite by id every
curated rule you relied on, AND copy 1-2 verbatim sentences from any
excerpt that grounds a blocker or warning into the `citations` array.
Return JSON only.
"""


# ------------------------- JSON parsing -------------------------

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_verdict(raw: str, load_id: int, excerpts: list[dict]) -> ComplianceVerdict:
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences if the model added them
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
        cited_excerpts=_resolve_citations(data.get("citations", []), excerpts),
        sanity_overrides=[],  # populated downstream by apply_sanity_layer
    )


def _resolve_citations(raw_citations: list, excerpts: list[dict]) -> list[ExcerptCitation]:
    """Match the LLM's `citations` entries against the excerpts we offered.

    Drops citations whose `source_id` we never showed (hallucinated sources).
    Truncates `snippet` to `SNIPPET_CHAR_BUDGET` chars. If the LLM omitted a
    snippet but cited a real source, fall back to the chunk head.
    """
    by_source: dict[str, dict] = {}
    for e in excerpts:
        sid = e["metadata"]["source_id"]
        by_source.setdefault(sid, e)  # first-wins keeps the closest excerpt

    out: list[ExcerptCitation] = []
    seen: set[tuple[str, str]] = set()
    for c in raw_citations or []:
        if not isinstance(c, dict):
            continue
        sid = str(c.get("source_id") or "").strip()
        excerpt = by_source.get(sid)
        if not excerpt:
            continue
        snippet = str(c.get("snippet") or "").strip()
        if not snippet:
            snippet = excerpt["text"][:SNIPPET_CHAR_BUDGET]
        snippet = snippet[:SNIPPET_CHAR_BUDGET]
        key = (sid, snippet[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(ExcerptCitation(
            source_id=sid,
            citation=excerpt["metadata"]["citation"],
            language=excerpt["metadata"]["language"],
            snippet=snippet,
            distance=float(excerpt["distance"]),
        ))
    return out


# ------------------------- deterministic mock evaluator -------------------------

# All rule predicates live in `sanity_check`. The mock evaluator and the
# post-LLM sanity layer share the same code, so there is exactly one source of
# truth for the hard rules.

def _evaluate_mock(truck: TruckSnapshot, load: LoadSnapshot) -> ComplianceVerdict:
    from app.agents.sanity_check import hard_rules_verdict

    hard = hard_rules_verdict(truck, load)
    is_compliant = hard["is_compliant"]
    confidence = 0.95 if is_compliant else 0.92  # mock is deterministic

    cited = list(hard["cited_rule_ids"])
    if is_compliant and not cited:
        cited = ["temp.chilled-band"]  # default citation if everything's trivially clean

    reasoning = (
        f"Mock-LLM analyst: {'COMPLIANT' if is_compliant else 'NOT COMPLIANT'} for truck "
        f"{truck['plate_number']} (last={truck['last_cargo']}, cap={truck['temp_capability']}) "
        f"vs load #{load['id']} {load['cargo_type']} {load['pickup_city']}->{load['delivery_city']}. "
        + (f"Blockers: {'; '.join(hard['blockers'])}." if hard["blockers"]
           else "All capability, logger, and prior-cargo rules satisfied.")
    )

    return ComplianceVerdict(
        load_id=load["id"],
        is_compliant=is_compliant,
        confidence=confidence,
        blockers=hard["blockers"],
        warnings=hard["warnings"],
        reasoning=reasoning,
        cited_rule_ids=cited,
        cited_excerpts=[],          # mock evaluator never quotes primary sources
        sanity_overrides=[],         # mock IS the deterministic layer; nothing to override
    )


# ------------------------- orchestrator -------------------------

def _resolve_provider(state: WorkflowState) -> LLMProvider:
    """Pick the LLM provider for this run.

    `use_mock_llm=True` on the state forces the deterministic mock regardless
    of which API keys are available — that's how `--mock-llm` and the test
    suites pin behaviour. Otherwise we defer to the env-driven factory.
    """
    if state.get("use_mock_llm"):
        return MockProvider()
    return get_provider()


def analyst_node(state: WorkflowState) -> dict:
    from app.agents.sanity_check import apply_sanity_layer, hard_rules_verdict

    truck = state["truck"]
    loads = state.get("available_loads", [])
    provider = _resolve_provider(state)
    use_mock = isinstance(provider, MockProvider)

    started = time.perf_counter()
    verdicts: list[ComplianceVerdict] = []
    rag_hits = 0
    corpus_hits = 0
    llm_calls = 0
    cache_hits = 0
    parse_errors = 0
    sanity_overrides_count = 0

    for load in loads:
        query = _build_query(truck, load)
        rules = query_rules(query, k=5)
        rag_hits += len(rules)

        if use_mock:
            verdicts.append(_evaluate_mock(truck, load))
            continue

        excerpts = query_corpus(query, k=3)
        corpus_hits += len(excerpts)

        try:
            raw, was_cached = provider.evaluate(
                _SYSTEM_PROMPT,
                _build_user_message(truck, load, rules, excerpts),
            )
            if was_cached:
                cache_hits += 1
            else:
                llm_calls += 1
            llm_verdict = _parse_verdict(raw, load["id"], excerpts)
            hard = hard_rules_verdict(truck, load)
            verdict, overrides = apply_sanity_layer(llm_verdict, hard, truck, load)
            if overrides:
                sanity_overrides_count += 1
            verdicts.append(verdict)
        except Exception as exc:
            parse_errors += 1
            verdicts.append(ComplianceVerdict(
                load_id=load["id"],
                is_compliant=False,
                confidence=0.0,
                blockers=[f"analyst failed: {type(exc).__name__}: {exc}"],
                warnings=[],
                reasoning="LLM call or JSON parse failed; treating as non-compliant.",
                cited_rule_ids=[],
                cited_excerpts=[],
                sanity_overrides=[],
            ))

    analyst_log: dict[str, Any] = {
        "mode": provider.name,
        "model": None if use_mock else f"{provider.name}:{provider.model}",
        "evaluated_loads": len(verdicts),
        "compliant_count": sum(1 for v in verdicts if v["is_compliant"]),
        "rag_hits": rag_hits,
        "corpus_hits": corpus_hits,
        "llm_calls": llm_calls,
        "cache_hits": cache_hits,
        "parse_errors": parse_errors,
        "sanity_overrides_count": sanity_overrides_count,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    return {"compliance_results": verdicts, "analyst_log": analyst_log}

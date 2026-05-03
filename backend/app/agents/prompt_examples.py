"""Few-shot worked examples appended to the Analyst's system prompt.

Each example shows a complete TRUCK + CANDIDATE LOAD pair followed by the
expected JSON verdict. The examples are chosen to disambiguate the two
reasoning failures Gemini Flash repeatedly makes on this corpus:

  1. Forbidden-cargo direction confusion — Gemini conflates "load IS chemicals"
     with "load forbids chemicals priors".
  2. ANSVSA wash-override missed — Gemini fails to apply the wash certificate
     that should unblock raw_meat → dairy/produce after sanitisation.

A third example shows a clean compliant case so the model learns the format
for the happy path too.
"""
from __future__ import annotations

# Note: examples are deliberately compact. The TRUCK / LOAD blocks mirror the
# real prompt structure but with fewer fields, so token cost stays low.

_EXAMPLE_1_BLOCKED_LOGGER_MISSING = """\
Example 1 — BLOCKED (capability + logger):

TRUCK
Plate: B-101-CBO  Capability: chilled  Last cargo: dairy
Calibrated pharma logger: False  Wash certs: (none)

CANDIDATE LOAD (id=99)
Cargo type: pharma  Required temperature: 2.0 to 8.0 C
Requires pharma logger: True
Forbidden prior cargo: chemicals,raw_meat,raw_poultry

Expected verdict:
{
  "is_compliant": false,
  "confidence": 0.95,
  "blockers": [
    "temp_capability=chilled cannot carry pharma (needs pharma_2_8 or multi_temp)",
    "pharma load requires a calibrated logger; truck has none"
  ],
  "warnings": [],
  "reasoning": "Pharma 2-8°C cargo demands a pharma_2_8 or multi_temp truck plus a calibrated logger; this chilled truck has neither.",
  "cited_rule_ids": ["temp.chilled-band", "gdp.pharma-temperature-and-logger"],
  "citations": [...]
}
"""

_EXAMPLE_2_WASH_OVERRIDE = """\
Example 2 — COMPLIANT via wash override (the wash-cert case the system MUST get right):

TRUCK
Plate: OR-404-CBO  Capability: multi_temp  Last cargo: raw_meat
Wash certs: ANSVSA-2024-0042 (wash_type=ansvsa_official, prior_cargo=raw_meat, VALID until 2026-05-04)

CANDIDATE LOAD (id=15)
Cargo type: dairy  Required temperature: 2.0 to 6.0 C
Forbidden prior cargo: raw_meat,raw_poultry,chemicals

Expected verdict:
{
  "is_compliant": true,
  "confidence": 0.92,
  "blockers": [],
  "warnings": [
    "prior cargo raw_meat normally forbidden, unblocked by valid ANSVSA wash certificate ANSVSA-2024-0042"
  ],
  "reasoning": "Although raw_meat is on the load's forbidden_prior_cargo list, the truck holds a currently-valid ANSVSA-official wash certificate covering raw_meat, which discharges the cross-contamination risk for dairy/produce/ambient_dry per haccp.raw-meat-to-non-meat-requires-ansvsa-wash.",
  "cited_rule_ids": ["haccp.raw-meat-to-non-meat-requires-ansvsa-wash", "ansvsa.wash-certificate-validity"],
  "citations": [...]
}
"""

_EXAMPLE_3_FORBIDDEN_DIRECTION = """\
Example 3 — COMPLIANT despite scary-looking forbidden_prior_cargo (direction disambiguation):

TRUCK
Plate: B-909-CBO  Capability: chilled  Last cargo: raw_meat
Wash certs: (none)

CANDIDATE LOAD (id=4)
Cargo type: raw_meat  Required temperature: 0.0 to 4.0 C
Forbidden prior cargo: chemicals      <-- the load forbids chemicals priors only

Expected verdict:
{
  "is_compliant": true,
  "confidence": 0.94,
  "blockers": [],
  "warnings": [],
  "reasoning": "The load's forbidden_prior_cargo list is {chemicals}; truck's last_cargo is raw_meat, which is NOT in that set. Raw_meat → raw_meat continuation is permitted under haccp.raw-meat-continuation. Capability and temperature window match.",
  "cited_rule_ids": ["haccp.raw-meat-continuation", "temp.chilled-band"],
  "citations": [...]
}
"""

WORKED_EXAMPLES = "\n".join([
    _EXAMPLE_1_BLOCKED_LOGGER_MISSING,
    _EXAMPLE_2_WASH_OVERRIDE,
    _EXAMPLE_3_FORBIDDEN_DIRECTION,
])

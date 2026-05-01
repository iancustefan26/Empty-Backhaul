"""Hand-written compliance rule corpus for the RAG layer.

These are intentionally synthetic / paraphrased rules, not legal text. They
cover the principal compliance dimensions the Analyst agent must reason over:

  * HACCP cross-contamination (raw meat -> non-meat food, fish -> dairy, etc.)
  * Romanian ANSVSA wash certificate validity
  * EU GDP rules for pharma 2-8 °C transports
  * EU 561/2006 driver hours
  * Temperature-band capability matching
  * Forbidden prior cargo declarations on a load
  * CMR documentation prerequisites

Each rule is ingested into Chroma with its `text` as the embedding source and
the rest as metadata so it can be filtered or cited by id.
"""
from __future__ import annotations

from typing import TypedDict


class ComplianceRule(TypedDict):
    id: str
    title: str
    text: str
    regulation: str
    severity: str          # "blocker" | "warning"
    applies_to: str        # comma-joined cargo classes for Chroma metadata


COMPLIANCE_RULES: list[ComplianceRule] = [
    {
        "id": "haccp.raw-meat-to-non-meat-requires-ansvsa-wash",
        "title": "Raw meat -> non-meat food requires ANSVSA wash certificate",
        "text": (
            "When a refrigerated truck has just transported raw_meat or raw_poultry, "
            "it MAY NOT be used for dairy, produce, ambient food, or pharmaceutical "
            "cargo until it has been sanitised at an ANSVSA-authorised wash station. "
            "The wash certificate must be of type 'ansvsa_official' and still within "
            "its validity window at the time the new cargo is loaded. Any other wash "
            "type (standard, deep) is insufficient."
        ),
        "regulation": "HACCP / ANSVSA Order 28/2017",
        "severity": "blocker",
        "applies_to": "raw_meat,raw_poultry,dairy,produce,pharma,ambient_dry",
    },
    {
        "id": "haccp.raw-meat-continuation",
        "title": "Raw meat trucks may continue with raw meat / poultry",
        "text": (
            "A truck whose previous cargo was raw_meat or raw_poultry MAY continue "
            "directly with another raw_meat or raw_poultry load without requiring "
            "an ANSVSA-grade wash, provided the temperature regime (0-4 °C) is "
            "maintained and the trailer interior shows no visible contamination."
        ),
        "regulation": "HACCP",
        "severity": "warning",
        "applies_to": "raw_meat,raw_poultry",
    },
    {
        "id": "haccp.chemicals-quarantine",
        "title": "Chemicals quarantine: never reuse for food without full ANSVSA decontamination",
        "text": (
            "If a truck's last_cargo was 'chemicals', no food-grade or pharmaceutical "
            "load may be placed on it irrespective of subsequent cleaning. Only an "
            "ANSVSA-grade decontamination procedure followed by a 24-hour ventilation "
            "cycle reopens the unit for food carriage. A standard or deep wash is "
            "explicitly NOT sufficient."
        ),
        "regulation": "HACCP / ANSVSA",
        "severity": "blocker",
        "applies_to": "chemicals,dairy,produce,pharma,ambient_dry,raw_meat,raw_poultry",
    },
    {
        "id": "gdp.pharma-temperature-and-logger",
        "title": "Pharma 2-8 °C requires calibrated logger + correct capability",
        "text": (
            "Pharmaceutical cargo in the 2-8 °C band requires a vehicle whose "
            "temp_capability is 'pharma_2_8' or 'multi_temp', AND a calibrated "
            "continuous temperature data logger flagged as has_pharma_logger=True. "
            "Trucks lacking either condition must be rejected for pharma loads."
        ),
        "regulation": "EU GDP 2013/C 343/01",
        "severity": "blocker",
        "applies_to": "pharma",
    },
    {
        "id": "gdp.pharma-cleanliness",
        "title": "Pharma transports require a clean cargo history",
        "text": (
            "Pharmaceutical transports must follow either a 'clean' / 'pharma' prior "
            "cargo OR a fully sanitised trailer with an ANSVSA-grade wash certificate. "
            "Any prior cargo of raw_meat, raw_poultry, dairy, produce, frozen_fish, "
            "or chemicals without such a certificate disqualifies the truck."
        ),
        "regulation": "EU GDP 2013/C 343/01",
        "severity": "blocker",
        "applies_to": "pharma",
    },
    {
        "id": "ansvsa.wash-certificate-validity",
        "title": "Wash certificates must be currently valid",
        "text": (
            "A wash certificate is only effective between its issued_at and "
            "valid_until timestamps. An expired certificate is treated as if no "
            "certificate exists. The certificate's prior_cargo field should match "
            "the truck's last_cargo for it to apply."
        ),
        "regulation": "ANSVSA",
        "severity": "blocker",
        "applies_to": "raw_meat,raw_poultry,chemicals,dairy,produce,pharma",
    },
    {
        "id": "eu561.driver-hours",
        "title": "Driver remaining hours must cover full route + buffer",
        "text": (
            "Per EU Regulation 561/2006, a driver may drive at most 9 hours per day "
            "(extendable to 10 hours twice a week). The truck's remaining_driving_hours "
            "must cover the full empty deadhead plus the loaded leg from pickup to "
            "delivery, with at least a 30-minute residual buffer for traffic and "
            "manoeuvres. Loads requiring longer drives than the buffer allows must "
            "be rejected or scheduled for the next driving day."
        ),
        "regulation": "EU 561/2006",
        "severity": "blocker",
        "applies_to": "any",
    },
    {
        "id": "temp.frozen-band",
        "title": "Frozen cargo must travel at <= -18 °C",
        "text": (
            "Frozen products such as frozen_vegetables and frozen_fish require "
            "continuous transport at or below -18 °C. The truck's temp_capability "
            "must be 'frozen' or 'multi_temp'. 'chilled', 'pharma_2_8', and 'ambient' "
            "trucks are not eligible."
        ),
        "regulation": "HACCP / EU 853/2004",
        "severity": "blocker",
        "applies_to": "frozen_vegetables,frozen_fish",
    },
    {
        "id": "temp.chilled-band",
        "title": "Chilled cargo requires 0-7 °C capability",
        "text": (
            "Dairy, fresh meat and chilled produce require a sustained 0-7 °C "
            "envelope (subclass-dependent). Eligible temp_capability values are "
            "'chilled', 'multi_temp', and 'pharma_2_8'. 'frozen'-only trucks may "
            "not carry chilled cargo unless reconfigured at the depot. 'ambient' "
            "trucks are categorically excluded."
        ),
        "regulation": "HACCP / EU 853/2004",
        "severity": "blocker",
        "applies_to": "dairy,produce,raw_meat,raw_poultry",
    },
    {
        "id": "temp.ambient-restrictions",
        "title": "Ambient-only trucks cannot carry temperature-controlled cargo",
        "text": (
            "Ambient (non-temperature-controlled) cargo MAY be carried by any truck. "
            "However, trucks with temp_capability='ambient' MUST NOT be used for "
            "chilled, frozen, or pharma cargo regardless of cleanliness, since they "
            "lack the required cooling envelope."
        ),
        "regulation": "HACCP",
        "severity": "blocker",
        "applies_to": "dairy,produce,pharma,frozen_vegetables,frozen_fish,raw_meat,raw_poultry",
    },
    {
        "id": "load.forbidden-prior-cargo-list",
        "title": "Load-declared forbidden prior cargo is a hard blocker",
        "text": (
            "Each load_request may declare a forbidden_prior_cargo list (e.g. "
            "'raw_meat,chemicals'). The Analyst MUST treat any match between the "
            "truck's last_cargo and an entry on this list as a hard blocker, even "
            "if a wash certificate would otherwise unblock that combination, unless "
            "another rule explicitly overrides (e.g. ANSVSA wash for raw_meat -> dairy)."
        ),
        "regulation": "Customer / shipper contract",
        "severity": "blocker",
        "applies_to": "any",
    },
    {
        "id": "ansvsa.cmr-documentation",
        "title": "CMR consignment note required for cross-county transports",
        "text": (
            "Every cross-county Romanian transport requires a CMR consignment note "
            "generated at pickup. For temperature-controlled cargo the CMR must "
            "reference the active wash certificate (if any) and the calibration "
            "certificate of the temperature logger. This is an issuance requirement "
            "and does not by itself block dispatch, but is mandatory at handover."
        ),
        "regulation": "ANSVSA / Romanian Government Decision 38/2008",
        "severity": "warning",
        "applies_to": "any",
    },
    {
        "id": "eu561.rest-stops",
        "title": "Mandatory 45-minute rest after 4.5 hours driving",
        "text": (
            "EU 561/2006 mandates a 45-minute rest break after at most 4.5 hours of "
            "accumulated driving, splittable into 15+30 minutes. Plan the deadhead "
            "+ loaded route accordingly: remaining_driving_hours measures actual "
            "wheel time and excludes mandatory breaks."
        ),
        "regulation": "EU 561/2006",
        "severity": "warning",
        "applies_to": "any",
    },
    {
        "id": "haccp.fish-cross-contamination",
        "title": "Frozen fish leaves an odour profile -- deep wash before dairy / produce / pharma",
        "text": (
            "Frozen_fish has a strong residual odour profile that easily transfers to "
            "neighbouring food cargo. After a frozen_fish load, a wash certificate of "
            "type 'deep', 'pharma_grade', or 'ansvsa_official' is required before "
            "loading dairy, produce, or pharma cargo."
        ),
        "regulation": "HACCP",
        "severity": "blocker",
        "applies_to": "frozen_fish,dairy,produce,pharma",
    },
]

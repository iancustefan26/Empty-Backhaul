"""Shared state schema for the LangGraph workflow."""
from __future__ import annotations

from typing import Any, TypedDict


class TruckSnapshot(TypedDict):
    id: int
    plate_number: str
    carrier_name: str | None
    temp_capability: str
    last_cargo: str
    has_pharma_logger: bool
    remaining_driving_hours: float
    status: str
    current_city: str
    home_base_city: str
    lat: float
    lon: float
    wash_certificates: list[dict[str, Any]]


class LoadSnapshot(TypedDict):
    id: int
    shipper_name: str | None
    cargo_type: str
    cargo_description: str | None
    temp_min_celsius: float
    temp_max_celsius: float
    requires_pharma_logger: bool
    forbidden_prior_cargo: str | None
    pickup_city: str
    delivery_city: str
    pickup_lat: float
    pickup_lon: float
    delivery_lat: float
    delivery_lon: float
    pickup_window_start: str
    pickup_window_end: str
    weight_kg: float
    price_eur: float
    status: str


class ComplianceVerdict(TypedDict):
    load_id: int
    is_compliant: bool
    confidence: float
    blockers: list[str]
    warnings: list[str]
    reasoning: str
    cited_rule_ids: list[str]


class StrategistDecision(TypedDict):
    chosen_load_id: int | None
    chosen_load: LoadSnapshot | None
    expected_margin_eur: float | None
    empty_detour_km: float | None
    loaded_km: float | None
    score_table: list[dict[str, Any]]
    optimiser_status: str
    explanation: str


class WorkflowState(TypedDict, total=False):
    # input
    truck_id: int
    use_mock_llm: bool

    # filled by Sentry
    truck: TruckSnapshot
    available_loads: list[LoadSnapshot]
    sentry_log: dict[str, Any]

    # filled by Analyst
    compliance_results: list[ComplianceVerdict]
    analyst_log: dict[str, Any]

    # filled by Strategist
    decision: StrategistDecision
    strategist_log: dict[str, Any]

    # error path
    error: str | None

// ---- Wire shapes returned by the FastAPI backend ----

export interface PointGeometry {
  type: "Point";
  coordinates: [number, number]; // [lon, lat]
}

export interface TruckProperties {
  plate_number: string;
  carrier_name: string | null;
  temp_capability: string;
  last_cargo: string;
  has_pharma_logger: boolean;
  remaining_driving_hours: number;
  status: string;
  current_city: string;
  home_base_city: string;
}

export interface TruckFeature {
  type: "Feature";
  id: number;
  geometry: PointGeometry | null;
  properties: TruckProperties;
}

export interface LoadProperties {
  shipper_name: string | null;
  cargo_type: string;
  cargo_description: string | null;
  temp_min_celsius: number;
  temp_max_celsius: number;
  requires_pharma_logger: boolean;
  forbidden_prior_cargo: string | null;
  pickup_city: string;
  delivery_city: string;
  delivery_lat: number;
  delivery_lon: number;
  weight_kg: number;
  price_eur: number;
  status: string;
  pickup_window_start: string;
  pickup_window_end: string;
}

export interface LoadFeature {
  type: "Feature";
  id: number;
  geometry: PointGeometry | null;
  properties: LoadProperties;
}

export interface FeatureCollection<F> {
  type: "FeatureCollection";
  feature_count: number;
  features: F[];
}

// ---- Match workflow state shape ----

export interface WashCertificate {
  certificate_number: string;
  issued_at: string;
  valid_until: string;
  wash_type: string;
  prior_cargo: string | null;
  issuing_facility: string | null;
  is_currently_valid: boolean;
}

export interface TruckSnapshot {
  id: number;
  plate_number: string;
  carrier_name: string | null;
  temp_capability: string;
  last_cargo: string;
  has_pharma_logger: boolean;
  remaining_driving_hours: number;
  status: string;
  current_city: string;
  home_base_city: string;
  lat: number;
  lon: number;
  wash_certificates: WashCertificate[];
}

export interface LoadSnapshot {
  id: number;
  shipper_name: string | null;
  cargo_type: string;
  cargo_description: string | null;
  temp_min_celsius: number;
  temp_max_celsius: number;
  requires_pharma_logger: boolean;
  forbidden_prior_cargo: string | null;
  pickup_city: string;
  delivery_city: string;
  pickup_lat: number;
  pickup_lon: number;
  delivery_lat: number;
  delivery_lon: number;
  pickup_window_start: string;
  pickup_window_end: string;
  weight_kg: number;
  price_eur: number;
  status: string;
}

export interface ExcerptCitation {
  source_id: string;
  citation: string;
  language: string;
  snippet: string;
  distance: number;
}

export interface ComplianceVerdict {
  load_id: number;
  is_compliant: boolean;
  confidence: number;
  blockers: string[];
  warnings: string[];
  reasoning: string;
  cited_rule_ids: string[];
  cited_excerpts?: ExcerptCitation[];
  sanity_overrides?: string[];
}

export interface ScoreRow {
  load_id: number;
  cargo_type: string;
  route: string;
  empty_detour_km: number;
  loaded_km: number;
  price_eur: number;
  estimated_cost_eur: number;
  expected_margin_eur: number;
  compliant: boolean;
  primary_blocker: string | null;
}

export interface StrategistDecision {
  chosen_load_id: number | null;
  chosen_load: LoadSnapshot | null;
  expected_margin_eur: number | null;
  empty_detour_km: number | null;
  loaded_km: number | null;
  score_table: ScoreRow[];
  optimiser_status: string;
  explanation: string;
}

export interface SentryLog {
  truck_status: string;
  available_load_count: number;
  wash_certificate_count: number;
  valid_wash_certificate_count: number;
  monitored_at: string;
}

export interface AnalystLog {
  mode: "mock" | "claude" | "gemini";
  model: string | null;
  evaluated_loads: number;
  compliant_count: number;
  rag_hits: number;
  corpus_hits?: number;
  llm_calls: number;
  cache_hits?: number;
  parse_errors: number;
  sanity_overrides_count?: number;
  elapsed_ms: number;
  completed_at: string;
}

export interface Documents {
  cmr: Record<string, unknown>;
  sanitization: Record<string, unknown>;
}

// ---- Fleet match (multi-truck assignment) ----

export interface TruckAssignment {
  truck_id: number;
  truck_plate: string;
  truck_current_city: string;
  load_id: number | null;
  load_pickup_city: string | null;
  load_delivery_city: string | null;
  cargo_type: string | null;
  source: string | null;
  empty_km: number;
  loaded_km: number;
  drive_hours: number;
  margin_eur: number;
}

export interface FleetPlanStats {
  rank: number;
  objective_value_cents: number;
  total_margin_eur: number;
  total_loaded_km: number;
  total_empty_km: number;
  total_km: number;
  deadhead_ratio: number;
  fleet_utilization_pct: number;
  customer_loads_served: number;
  customer_loads_available: number;
  broker_loads_served: number;
  broker_loads_available: number;
  unserved_customer_load_ids: number[];
  assignments: TruckAssignment[];
}

export interface FleetOptimiserResult {
  alternatives: FleetPlanStats[];
  optimiser_status: string;
  fleet_size: number;
  available_loads: number;
  candidate_pairs: number;
  elapsed_ms: number;
  notes: string[];
}

export interface FleetSentryLog {
  fleet_size: number;
  available_load_count: number;
  customer_loads: number;
  broker_loads: number;
  include_broker: boolean;
  monitored_at: string;
}

export interface FleetAnalystLog {
  mode: string;
  model: string | null;
  fleet_size: number;
  load_count: number;
  pair_count: number;
  pre_blocked_pairs: number;
  compliant_pairs: number;
  rag_hits: number;
  corpus_hits: number;
  llm_calls: number;
  cache_hits: number;
  parse_errors: number;
  sanity_corrections: number;
  elapsed_ms: number;
  completed_at: string;
}

export interface FleetMatchResponse {
  fleet: TruckSnapshot[];
  available_loads: LoadSnapshot[];
  sentry_log: FleetSentryLog;
  analyst_log: FleetAnalystLog;
  optimiser: FleetOptimiserResult;
  compliance_matrix: Array<ComplianceVerdict & { truck_id: number; load_id: number }>;
}


export interface MatchState {
  truck_id: number;
  use_mock_llm: boolean;
  truck: TruckSnapshot;
  available_loads: LoadSnapshot[];
  sentry_log: SentryLog;
  compliance_results: ComplianceVerdict[];
  analyst_log: AnalystLog;
  decision: StrategistDecision;
  strategist_log: Record<string, unknown>;
  documents: Documents;
  error?: string;
}

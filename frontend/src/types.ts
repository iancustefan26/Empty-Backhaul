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

export interface ComplianceVerdict {
  load_id: number;
  is_compliant: boolean;
  confidence: number;
  blockers: string[];
  warnings: string[];
  reasoning: string;
  cited_rule_ids: string[];
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
  mode: "mock" | "claude";
  model: string | null;
  evaluated_loads: number;
  compliant_count: number;
  rag_hits: number;
  llm_calls: number;
  parse_errors: number;
  elapsed_ms: number;
  completed_at: string;
}

export interface Documents {
  cmr: Record<string, unknown>;
  sanitization: Record<string, unknown>;
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

/**
 * Dispatcher-console-facing types. These are the shape the new UI components
 * (ChatPanel, DispatchMap, PlanDetail, nl-router) expect. They mirror the
 * Lovable bundle's vocabulary (`truck_id`, `load_id`, `forbidden_prior_cargo`
 * as an array of CargoType, etc.) so the components stay portable.
 *
 * `api-adapter.ts` translates the FastAPI responses (`id`, comma-separated
 * `forbidden_prior_cargo`, finer-grained cargo enum) into this shape.
 */

export type CargoType =
  | "pharma"
  | "dairy"
  | "frozen"
  | "raw_meat"
  | "produce"
  | "general";

export type LoadSource = "customer" | "broker";

export interface TruckSnapshot {
  truck_id: number;
  plate_number: string;
  carrier_name: string;
  temp_capability: string;
  last_cargo: CargoType | null;
  has_pharma_logger: boolean;
  remaining_driving_hours: number;
  status: string;
  current_city: string;
  home_base_city: string;
  lat: number;
  lon: number;
}

export interface LoadSnapshot {
  load_id: number;
  shipper_name: string;
  cargo_type: CargoType;
  cargo_description: string;
  temp_min_celsius: number;
  temp_max_celsius: number;
  requires_pharma_logger: boolean;
  forbidden_prior_cargo: CargoType[];
  pickup_city: string;
  delivery_city: string;
  pickup_lat: number;
  pickup_lon: number;
  delivery_lat: number;
  delivery_lon: number;
  weight_kg: number;
  price_eur: number;
  status: string;
  source: LoadSource;
  pickup_window_start: string;
  pickup_window_end: string;
}

export interface RouteLeg {
  from_city: string;
  to_city: string;
  from_lat: number;
  from_lon: number;
  to_lat: number;
  to_lon: number;
  km: number;
  kind: "empty" | "loaded";
  load_id: number | null;
}

export type PlanKind = "IDLE" | "SINGLE" | "CHAIN";

export interface VanPlan {
  kind: PlanKind;
  van_id: number;
  van_plate: string;
  load_ids: number[];
  total_km: number;
  empty_km: number;
  loaded_km: number;
  drive_hours: number;
  margin_eur: number;
  legs: RouteLeg[];
}

export interface PlanAlternative {
  rank: number;
  total_fleet_margin_eur: number;
  total_loaded_km: number;
  total_empty_km: number;
  total_km: number;
  deadhead_ratio: number;
  fleet_utilization_pct: number;
  single_trips_count: number;
  chain_trips_count: number;
  idle_count: number;
  customer_loads_served: number;
  customer_loads_available: number;
  broker_loads_served: number;
  broker_loads_available: number;
  unserved_customer_load_ids: number[];
  plans: VanPlan[];
}

export interface PlanResponse {
  depot: { city: string; lat: number; lon: number };
  fleet: TruckSnapshot[];
  available_loads: LoadSnapshot[];
  optimiser: {
    optimiser_status: string;
    elapsed_ms: number;
    alternatives: PlanAlternative[];
  };
  generated_at: string;
}

export interface PlanOptions {
  include_broker?: boolean;
  enable_chains?: boolean;
  fleet_size?: number;
  horizon_days?: number;
  skip_cargo?: CargoType[];
  optimize_for?: "profit" | "sla";
}

export type ChatPayload =
  | { kind: "plan"; plan: PlanResponse; options: PlanOptions; activeRank?: number }
  | { kind: "idle_explain"; van_plate: string; reasons: string[] }
  | { kind: "compliance"; saved_eur: number; violations: { rule: string; fine_eur: number }[] }
  | { kind: "clarify"; suggestions: string[] }
  | { kind: "text" };

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  payload?: ChatPayload | null;
  created_at: string;
}

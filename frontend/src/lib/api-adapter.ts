/**
 * Bridges FastAPI backend shapes (`backend/app/api/*`) into the
 * dispatcher-console types (`dispatch-types.ts`). The two diverge in:
 *
 *   - id field name (backend `id` vs dispatch `truck_id`/`load_id`)
 *   - cargo enum granularity (backend has `frozen_vegetables`, `frozen_fish`,
 *     `ambient_dry`, `chemicals`, `raw_poultry`; dispatch UI collapses
 *     these to `frozen` / `general` / `raw_meat`)
 *   - `forbidden_prior_cargo` representation (backend: comma-separated
 *     string or null; dispatch: CargoType[])
 *
 * Everything goes through this one module so the rest of the frontend
 * can treat backend changes as a one-place migration.
 */
import type {
  CargoType,
  LoadSnapshot,
  PlanAlternative,
  PlanOptions,
  PlanResponse,
  RouteLeg,
  TruckSnapshot,
  VanPlan,
} from "./dispatch-types";

// ---------------------------------------------------------------------------
// Cargo enum mapping
// ---------------------------------------------------------------------------

const CARGO_MAP: Record<string, CargoType> = {
  pharma: "pharma",
  dairy: "dairy",
  produce: "produce",
  raw_meat: "raw_meat",
  raw_poultry: "raw_meat",
  frozen: "frozen",
  frozen_vegetables: "frozen",
  frozen_fish: "frozen",
  ambient_dry: "general",
  chemicals: "general",
  general: "general",
  clean: "general",
};

function toCargoType(raw: string | null | undefined): CargoType {
  if (!raw) return "general";
  return CARGO_MAP[raw] ?? "general";
}

function toCargoArray(raw: string | null | undefined): CargoType[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(toCargoType);
}

// ---------------------------------------------------------------------------
// /api/route/plan response → PlanResponse
// ---------------------------------------------------------------------------

interface RawTruck {
  id: number;
  plate_number: string;
  carrier_name: string | null;
  temp_capability: string;
  last_cargo: string | null;
  has_pharma_logger: boolean;
  remaining_driving_hours: number;
  status: string;
  current_city: string;
  home_base_city: string;
  lat: number;
  lon: number;
}

interface RawLoad {
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
  weight_kg: number;
  price_eur: number;
  status: string;
  source: string | null;
  pickup_window_start: string;
  pickup_window_end: string;
}

interface RawLeg {
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

interface RawVanPlan {
  kind: "IDLE" | "SINGLE" | "CHAIN";
  van_id: number;
  van_plate: string;
  load_ids: number[];
  total_km: number;
  empty_km: number;
  loaded_km: number;
  drive_hours: number;
  margin_eur: number;
  legs: RawLeg[];
}

interface RawAlternative {
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
  plans: RawVanPlan[];
}

interface RawPlanResponse {
  depot: { city: string; lat: number; lon: number };
  fleet: RawTruck[];
  available_loads: RawLoad[];
  optimiser: {
    optimiser_status: string;
    elapsed_ms: number;
    alternatives: RawAlternative[];
  };
}

function adaptTruck(t: RawTruck): TruckSnapshot {
  return {
    truck_id: t.id,
    plate_number: t.plate_number,
    carrier_name: t.carrier_name ?? "Unknown carrier",
    temp_capability: t.temp_capability,
    last_cargo: t.last_cargo ? toCargoType(t.last_cargo) : null,
    has_pharma_logger: t.has_pharma_logger,
    remaining_driving_hours: t.remaining_driving_hours,
    status: t.status,
    current_city: t.current_city,
    home_base_city: t.home_base_city,
    lat: t.lat,
    lon: t.lon,
  };
}

function adaptLoad(l: RawLoad): LoadSnapshot {
  return {
    load_id: l.id,
    shipper_name: l.shipper_name ?? `Shipper #${l.id}`,
    cargo_type: toCargoType(l.cargo_type),
    cargo_description: l.cargo_description ?? "",
    temp_min_celsius: l.temp_min_celsius,
    temp_max_celsius: l.temp_max_celsius,
    requires_pharma_logger: l.requires_pharma_logger,
    forbidden_prior_cargo: toCargoArray(l.forbidden_prior_cargo),
    pickup_city: l.pickup_city,
    delivery_city: l.delivery_city,
    pickup_lat: l.pickup_lat,
    pickup_lon: l.pickup_lon,
    delivery_lat: l.delivery_lat,
    delivery_lon: l.delivery_lon,
    weight_kg: l.weight_kg,
    price_eur: l.price_eur,
    status: l.status,
    source: (l.source as "customer" | "broker" | null) ?? "customer",
    pickup_window_start: l.pickup_window_start,
    pickup_window_end: l.pickup_window_end,
  };
}

function adaptLeg(leg: RawLeg): RouteLeg {
  return { ...leg };
}

function adaptVanPlan(p: RawVanPlan): VanPlan {
  return {
    kind: p.kind,
    van_id: p.van_id,
    van_plate: p.van_plate,
    load_ids: p.load_ids,
    total_km: p.total_km,
    empty_km: p.empty_km,
    loaded_km: p.loaded_km,
    drive_hours: p.drive_hours,
    margin_eur: p.margin_eur,
    legs: p.legs.map(adaptLeg),
  };
}

function adaptAlternative(a: RawAlternative): PlanAlternative {
  return {
    rank: a.rank,
    total_fleet_margin_eur: a.total_fleet_margin_eur,
    total_loaded_km: a.total_loaded_km,
    total_empty_km: a.total_empty_km,
    total_km: a.total_km,
    deadhead_ratio: a.deadhead_ratio,
    fleet_utilization_pct: a.fleet_utilization_pct,
    single_trips_count: a.single_trips_count,
    chain_trips_count: a.chain_trips_count,
    idle_count: a.idle_count,
    customer_loads_served: a.customer_loads_served,
    customer_loads_available: a.customer_loads_available,
    broker_loads_served: a.broker_loads_served,
    broker_loads_available: a.broker_loads_available,
    unserved_customer_load_ids: a.unserved_customer_load_ids,
    plans: a.plans.map(adaptVanPlan),
  };
}

function adaptPlanResponse(raw: RawPlanResponse): PlanResponse {
  return {
    depot: raw.depot,
    fleet: raw.fleet.map(adaptTruck),
    available_loads: raw.available_loads.map(adaptLoad),
    optimiser: {
      optimiser_status: raw.optimiser.optimiser_status,
      elapsed_ms: raw.optimiser.elapsed_ms,
      alternatives: raw.optimiser.alternatives.map(adaptAlternative),
    },
    generated_at: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch { /* noop */ }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export interface FetchPlanOptions extends PlanOptions {
  mockLlm?: boolean;
}

/**
 * Hits POST /api/route/plan with the dispatcher's options and returns
 * the dispatch-typed PlanResponse. Skips client-only options the
 * backend doesn't (yet) understand.
 */
export async function fetchPlan(opts: FetchPlanOptions = {}): Promise<PlanResponse> {
  const params = new URLSearchParams();
  params.set("top_k", "3");
  params.set("include_broker", String(opts.include_broker !== false));
  params.set("enable_chains", String(opts.enable_chains !== false));
  params.set("mock_llm", String(opts.mockLlm !== false));
  if (typeof opts.fleet_size === "number") {
    params.set("fleet_size", String(Math.max(1, Math.min(15, opts.fleet_size))));
  }
  // skip_cargo / optimize_for / horizon_days don't have backend params yet —
  // the chat layer renders them in the human label so the dispatcher knows
  // the request was understood.
  const raw = await getJson<RawPlanResponse>(
    `/api/route/plan?${params.toString()}`,
    { method: "POST" },
  );
  return adaptPlanResponse(raw);
}

/**
 * Pre-baked compliance-value summary derived from PR4 Experiment B.
 * Static for now — the backend has the live numbers under
 * `backend/docs/experiments/exp_b.json` but the frontend doesn't
 * call that endpoint yet. Updating the figures here keeps the chat
 * answer accurate without the round-trip.
 */
export function complianceSnapshot() {
  return {
    saved_eur: 5000,
    violations: [
      { rule: "haccp.chemicals-quarantine", fine_eur: 2000 },
      { rule: "temp.chilled-band", fine_eur: 2500 },
      { rule: "temp.ambient-restrictions", fine_eur: 2500 },
      { rule: "load.forbidden-prior-cargo-list", fine_eur: 1000 },
    ],
  };
}

/**
 * Heuristic explanation for "why is van X idle?". Looks at the most
 * recent plan to see if the van is in there; if not assigned, lists
 * common reasons. The real backend reasoning lives at
 * /api/match/{truck_id} — we'll wire that for the demo answer.
 */
export function explainIdleHeuristic(plate: string, plan: PlanResponse | null): string[] {
  const reasons: string[] = [];
  const truck = plan?.fleet.find(
    (t) => t.plate_number.toLowerCase() === plate.toLowerCase(),
  );
  if (!truck) {
    reasons.push("I can't find that van in today's fleet snapshot.");
    return reasons;
  }
  if (plan) {
    const alt = plan.optimiser.alternatives[0];
    const inPlan = alt?.plans.find((p) => p.van_plate === truck.plate_number);
    if (!inPlan || inPlan.kind === "IDLE") {
      reasons.push(`No profitable round-trip exists for ${truck.plate_number} from the depot today.`);
    } else {
      reasons.push(`Actually, ${truck.plate_number} IS planned today: ${inPlan.kind.toLowerCase()} trip, €${inPlan.margin_eur.toFixed(2)} margin.`);
      return reasons;
    }
  }
  if (truck.last_cargo === "raw_meat") {
    reasons.push("Last cargo was raw meat — needs ANSVSA wash before it can carry dairy/produce.");
  }
  if (truck.last_cargo === "general" && truck.temp_capability === "ambient") {
    reasons.push("Ambient-only van with chemicals history — HACCP blocks all food-grade reuse today.");
  }
  if (!truck.has_pharma_logger && truck.temp_capability.startsWith("pharma")) {
    reasons.push("Pharma 2-8°C trips need a calibrated logger — this van doesn't have one.");
  }
  if (reasons.length === 0) {
    reasons.push("Capability + last-cargo + driver-hours combination didn't yield a profitable round-trip from the depot.");
  }
  return reasons;
}

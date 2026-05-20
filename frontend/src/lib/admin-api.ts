/**
 * Thin client for the dispatcher console's admin endpoints
 * (POST /api/admin/...). Powers the FleetManager modal.
 *
 * Every mutation here also clears the verdict cache server-side (the
 * admin router handles that), so the next `fetchPlan()` re-evaluates
 * against the new data. No frontend-side cache invalidation needed.
 */

// ---------------------------------------------------------------------------
// Shape mirrors the backend Pydantic models in app/api/admin.py
// ---------------------------------------------------------------------------

export interface AdminTruckIn {
  plate_number: string;
  carrier_name?: string;
  temp_capability: string;
  last_cargo: string;
  has_pharma_logger?: boolean;
  remaining_driving_hours?: number;
  status?: string;
  home_base_city?: string;
  current_city?: string;
}

export interface AdminLoadIn {
  shipper_name?: string;
  cargo_type: string;
  cargo_description?: string;
  temp_min_celsius: number;
  temp_max_celsius: number;
  requires_pharma_logger?: boolean;
  forbidden_prior_cargo?: string | null;
  pickup_city: string;
  delivery_city: string;
  pickup_window_start: string;   // ISO
  pickup_window_end: string;     // ISO
  weight_kg: number;
  price_eur: number;
  source?: "customer" | "broker";
}

export interface TruckRow {
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
}

export interface LoadRow {
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
  pickup_window_start: string;
  pickup_window_end: string;
  weight_kg: number;
  price_eur: number;
  status: string;
  source: string;
  pickup_lat: number;
  pickup_lon: number;
  delivery_lat: number;
  delivery_lon: number;
}

export interface AdminEnums {
  truck_capabilities: string[];
  truck_last_cargoes: string[];
  cargo_types: string[];
  cities: string[];
  load_sources: ("customer" | "broker")[];
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function _json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* */ }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

const J = { "content-type": "application/json" };

// ---------------------------------------------------------------------------
// Trucks
// ---------------------------------------------------------------------------

export const listTrucks = (): Promise<TruckRow[]> =>
  _json<TruckRow[]>("/api/admin/trucks");

export const createTruck = (body: AdminTruckIn): Promise<TruckRow> =>
  _json("/api/admin/trucks", { method: "POST", headers: J, body: JSON.stringify(body) });

export const deleteTruck = (id: number): Promise<{ deleted: number }> =>
  _json(`/api/admin/trucks/${id}`, { method: "DELETE" });

export const deleteAllTrucks = (): Promise<{ deleted: number }> =>
  _json("/api/admin/trucks", { method: "DELETE" });

export const randomTrucks = (count: number): Promise<{ created: number; trucks: TruckRow[] }> =>
  _json(`/api/admin/trucks/random?count=${count}`, { method: "POST" });

// ---------------------------------------------------------------------------
// Loads
// ---------------------------------------------------------------------------

export const listLoads = (): Promise<LoadRow[]> =>
  _json<LoadRow[]>("/api/admin/loads");

export const createLoad = (body: AdminLoadIn): Promise<LoadRow> =>
  _json("/api/admin/loads", { method: "POST", headers: J, body: JSON.stringify(body) });

export const deleteLoad = (id: number): Promise<{ deleted: number }> =>
  _json(`/api/admin/loads/${id}`, { method: "DELETE" });

export const deleteAllLoads = (): Promise<{ deleted: number }> =>
  _json("/api/admin/loads", { method: "DELETE" });

export const randomLoads = (count: number): Promise<{ created: number; loads: LoadRow[] }> =>
  _json(`/api/admin/loads/random?count=${count}`, { method: "POST" });

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

export const resetWorkspace = (): Promise<{ status: string }> =>
  _json("/api/admin/reset", { method: "POST" });

export const reseedCanonical = (): Promise<{ status: string; trucks: number; loads: number }> =>
  _json("/api/admin/seed", { method: "POST" });

export const fetchEnums = (): Promise<AdminEnums> =>
  _json<AdminEnums>("/api/admin/enums");

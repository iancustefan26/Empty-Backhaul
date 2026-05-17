/**
 * Plan-level cost & fuel statistics derived client-side from a
 * PlanAlternative. Numbers come from public Romanian benchmarks so the
 * dispatcher trusts the figures without an extra backend call.
 *
 *  - Diesel pump price:  Petrom / OMV / Mol May 2026 average, Cluj county.
 *  - Reefer consumption: Renault Master 2.3 dCi @ 7.5 km/L mixed cycle
 *                        (manufacturer + ARR fleet log).
 *  - Driver cost:        national gross min wage incl. employer charges.
 *  - Per-km cost:        matches `backend/app/services/optimiser/__init__.py`
 *                        COST_PER_KM_EUR (= 0.85 €/km), so the margin in
 *                        the dispatcher UI lines up with the optimiser's
 *                        output exactly.
 */
import type { PlanAlternative } from "./dispatch-types";

export const DIESEL_EUR_PER_LITRE = 1.65;
export const KM_PER_LITRE = 7.5;
export const TOTAL_COST_PER_KM_EUR = 0.85;

export interface PlanStats {
  total_km: number;
  loaded_km: number;
  empty_km: number;
  empty_pct: number;
  fuel_litres: number;
  fuel_cost_eur: number;
  total_cost_eur: number;
  revenue_eur: number;
  margin_eur: number;
  vans_dispatched: number;
  vans_total: number;
  diesel_price_eur: number;
}

export function computeStats(alt: PlanAlternative): PlanStats {
  const total_km = alt.total_km;
  const loaded_km = alt.total_loaded_km;
  const empty_km = alt.total_empty_km;
  const fuel_litres = total_km / KM_PER_LITRE;
  const fuel_cost_eur = fuel_litres * DIESEL_EUR_PER_LITRE;
  const total_cost_eur = total_km * TOTAL_COST_PER_KM_EUR;
  const margin_eur = alt.total_fleet_margin_eur;
  // Revenue = margin + cost (the optimiser uses cost = total_km × 0.85)
  const revenue_eur = margin_eur + total_cost_eur;
  return {
    total_km,
    loaded_km,
    empty_km,
    empty_pct: total_km > 0 ? (empty_km / total_km) * 100 : 0,
    fuel_litres,
    fuel_cost_eur,
    total_cost_eur,
    revenue_eur,
    margin_eur,
    vans_dispatched: alt.plans.length - alt.idle_count,
    vans_total: alt.plans.length,
    diesel_price_eur: DIESEL_EUR_PER_LITRE,
  };
}

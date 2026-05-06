import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { Fragment } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer } from "react-leaflet";

import {
  DayPlan,
  FleetPlanStats,
  LoadFeature,
  RoutePlanStats,
  TruckFeature,
} from "../types";
import { depotIcon, loadIcon, truckIcon } from "./icons";

// Distinct colour-blind-friendly palette cycled per assigned van so each
// route's polyline + arrows stay visually traceable end-to-end.
export const FLEET_COLOURS = [
  "#22d3ee", "#a78bfa", "#f59e0b", "#34d399", "#f472b6",
  "#60a5fa", "#fb7185", "#facc15", "#4ade80", "#c084fc",
  "#fda4af", "#fbbf24", "#84cc16", "#38bdf8", "#fb923c",
];

interface Props {
  trucks: TruckFeature[];
  loads: LoadFeature[];
  selectedTruckId: number | null;
  chosenLoadId: number | null;
  onSelectTruck: (id: number) => void;
  fleetPlan?: FleetPlanStats | null;       // PR3 single-load fleet plan
  routePlan?: RoutePlanStats | null;       // PR4 depot-based route plan
  depot?: { city: string | null; lat: number | null; lon: number | null } | null;
  vanColors?: Record<number, string>;
}

// ---------- Bearing + arrow helpers ----------

function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const toDeg = (r: number) => (r * 180) / Math.PI;
  const φ1 = toRad(lat1);
  const φ2 = toRad(lat2);
  const Δλ = toRad(lon2 - lon1);
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

function midpoint(
  lat1: number, lon1: number, lat2: number, lon2: number,
): [number, number] {
  return [(lat1 + lat2) / 2, (lon1 + lon2) / 2];
}

function arrowIcon(colour: string, bearing: number): L.DivIcon {
  // Leaflet marker rotation is not built-in; use a CSS transform on the
  // inner div. Bearing 0° = north → for ▲ pointing up we rotate by bearing.
  return L.divIcon({
    html: `<div style="transform: rotate(${bearing}deg); display:inline-block;
                color:${colour}; font-size:18px; line-height:1;
                text-shadow:0 0 3px rgba(0,0,0,0.85), 0 0 1px ${colour};
                font-weight:bold;">▲</div>`,
    className: "cbo-arrow-icon",
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

// ---------- Component ----------

export function Map({
  trucks,
  loads,
  selectedTruckId,
  chosenLoadId,
  onSelectTruck,
  fleetPlan,
  routePlan,
  depot,
  vanColors,
}: Props) {
  const chosenLoad = loads.find((l) => l.id === chosenLoadId);
  const selectedTruck = trucks.find((t) => t.id === selectedTruckId);
  const truckById: Record<number, TruckFeature> = Object.fromEntries(
    trucks.map((t) => [t.id, t]),
  );
  const loadById: Record<number, LoadFeature> = Object.fromEntries(
    loads.map((l) => [l.id, l]),
  );

  return (
    <MapContainer
      center={[45.9, 25.0]}
      zoom={6.5}
      scrollWheelZoom
      className="h-full w-full"
    >
      <TileLayer
        attribution='&copy; <a href="https://osm.org">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {/* Depot marker (route-plan mode only) */}
      {depot?.lat != null && depot?.lon != null && (
        <Marker position={[depot.lat, depot.lon]} icon={depotIcon()}>
          <Popup>
            <strong>Depot — {depot.city}</strong>
            <br />
            <em>Cluj Reefer Logistics</em>
            <br />
            All vans start and end here.
          </Popup>
        </Marker>
      )}

      {trucks.map((t) => {
        if (!t.geometry) return null;
        const [lon, lat] = t.geometry.coordinates;
        const p = t.properties;
        return (
          <Marker
            key={`t-${t.id}`}
            position={[lat, lon]}
            icon={truckIcon(p.status, t.id === selectedTruckId)}
            eventHandlers={{ click: () => onSelectTruck(t.id) }}
          >
            <Popup>
              <strong>{p.plate_number}</strong>
              <br />
              {p.carrier_name ?? "(carrier unknown)"}
              <br />
              capability: <code>{p.temp_capability}</code>
              <br />
              last cargo: <code>{p.last_cargo}</code>
              <br />
              status: <code>{p.status}</code>
            </Popup>
          </Marker>
        );
      })}

      {loads.map((l) => {
        if (!l.geometry) return null;
        const [lon, lat] = l.geometry.coordinates;
        const p = l.properties;
        return (
          <Marker
            key={`l-${l.id}`}
            position={[lat, lon]}
            icon={loadIcon(p.cargo_type, l.id === chosenLoadId)}
          >
            <Popup>
              <strong>
                Load #{l.id}: {p.cargo_type}
              </strong>
              <br />
              {p.cargo_description}
              <br />
              {p.pickup_city} → {p.delivery_city}
              <br />
              €{p.price_eur} · {p.weight_kg} kg
              {p.source && (
                <>
                  <br />
                  <em style={{ color: p.source === "broker" ? "#a78bfa" : "#10b981" }}>
                    {p.source} pool
                  </em>
                </>
              )}
            </Popup>
          </Marker>
        );
      })}

      {/* Route-plan polylines (depot model, with directional arrows) */}
      {routePlan &&
        routePlan.plans.map((plan, vanIdx) => {
          if (plan.kind === "IDLE") return null;
          const colour = vanColors?.[plan.van_id] ?? FLEET_COLOURS[vanIdx % FLEET_COLOURS.length];
          return (
            <Fragment key={`route-${plan.van_id}`}>
              {plan.legs.map((leg, legIdx) => {
                if (leg.km < 0.5) return null;   // skip 0-km legs (same-city)
                const positions: [number, number][] = [
                  [leg.from_lat, leg.from_lon],
                  [leg.to_lat, leg.to_lon],
                ];
                const isLoaded = leg.kind === "loaded";
                const arrowAt = midpoint(leg.from_lat, leg.from_lon, leg.to_lat, leg.to_lon);
                const heading = bearingDeg(
                  leg.from_lat, leg.from_lon, leg.to_lat, leg.to_lon,
                );
                return (
                  <Fragment key={`route-${plan.van_id}-leg-${legIdx}`}>
                    <Polyline
                      positions={positions}
                      pathOptions={{
                        color: colour,
                        weight: isLoaded ? 5 : 2.5,
                        opacity: isLoaded ? 0.95 : 0.65,
                        dashArray: isLoaded ? undefined : "6 8",
                      }}
                    />
                    <Marker position={arrowAt} icon={arrowIcon(colour, heading)} interactive={false} />
                  </Fragment>
                );
              })}
            </Fragment>
          );
        })}

      {/* PR3 fleet plan polylines (kept for the legacy /api/match/fleet path) */}
      {fleetPlan &&
        fleetPlan.assignments
          .filter((a) => a.load_id !== null)
          .map((a, i) => {
            const truck = truckById[a.truck_id];
            const load = a.load_id !== null ? loadById[a.load_id] : null;
            if (!truck?.geometry || !load?.geometry) return null;
            const colour = FLEET_COLOURS[i % FLEET_COLOURS.length];
            const truckLatLng: [number, number] = [
              truck.geometry.coordinates[1], truck.geometry.coordinates[0],
            ];
            const pickupLatLng: [number, number] = [
              load.geometry.coordinates[1], load.geometry.coordinates[0],
            ];
            const deliveryLatLng: [number, number] = [
              load.properties.delivery_lat, load.properties.delivery_lon,
            ];
            return (
              <Fragment key={`fleet-${a.truck_id}-${a.load_id}`}>
                {a.empty_km > 0.5 && (
                  <Polyline
                    positions={[truckLatLng, pickupLatLng]}
                    pathOptions={{ color: colour, weight: 2.5, dashArray: "4 6", opacity: 0.7 }}
                  />
                )}
                <Polyline
                  positions={[pickupLatLng, deliveryLatLng]}
                  pathOptions={{ color: colour, weight: 4, opacity: 0.9 }}
                />
              </Fragment>
            );
          })}

      {/* Single-truck legacy view (only when no fleet/route plan) */}
      {!routePlan &&
        !fleetPlan &&
        chosenLoad &&
        chosenLoad.geometry &&
        selectedTruck &&
        selectedTruck.geometry && (
          <>
            <Polyline
              positions={[
                [selectedTruck.geometry.coordinates[1], selectedTruck.geometry.coordinates[0]],
                [chosenLoad.geometry.coordinates[1], chosenLoad.geometry.coordinates[0]],
              ]}
              pathOptions={{
                color: "#6366f1", weight: 3, dashArray: "6 8", opacity: 0.85,
              }}
            />
            <Polyline
              positions={[
                [chosenLoad.geometry.coordinates[1], chosenLoad.geometry.coordinates[0]],
                [chosenLoad.properties.delivery_lat, chosenLoad.properties.delivery_lon],
              ]}
              pathOptions={{ color: "#f59e0b", weight: 4, opacity: 0.9 }}
            />
          </>
        )}
    </MapContainer>
  );
}

// Re-export DayPlan type so users don't need to import it separately
export type { DayPlan };

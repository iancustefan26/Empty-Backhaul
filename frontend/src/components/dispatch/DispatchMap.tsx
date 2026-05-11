/**
 * Map view for the dispatcher console. Shows the depot, the fleet, the
 * available loads, and (when a plan is active) per-van colour-coded route
 * polylines with directional separation between empty and loaded legs.
 *
 * Ported from the Lovable bundle; CARTO dark tiles, FitBounds on plan
 * change, depot pulse animation via the `.depot-marker` CSS class.
 */
import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { CARGO_EMOJI, vanColor } from "../../lib/van-colors";
import type {
  LoadSnapshot,
  PlanAlternative,
  TruckSnapshot,
} from "../../lib/dispatch-types";

const depotIcon = L.divIcon({
  className: "depot-marker-wrap",
  html: `<div class="depot-marker" style="width:28px;height:28px;background:#facc15;border:3px solid #78350f;display:flex;align-items:center;justify-content:center;font-size:16px;color:#3b2200;font-weight:900">★</div>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

function vanIcon(color: string, plate: string) {
  return L.divIcon({
    className: "van-marker",
    html: `<div style="display:flex;flex-direction:column;align-items:center;gap:2px"><div style="width:18px;height:18px;border-radius:50%;background:${color};border:2px solid #0f172a;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div><span style="font-size:9px;color:#e2e8f0;background:rgba(15,23,42,.85);padding:1px 4px;border-radius:3px;white-space:nowrap;font-weight:600">${plate.replace("-CRL", "")}</span></div>`,
    iconSize: [60, 32],
    iconAnchor: [30, 16],
  });
}

function loadIcon(load: LoadSnapshot, isPickup: boolean) {
  const emoji = CARGO_EMOJI[load.cargo_type] ?? "📦";
  const color = load.source === "customer" ? "#34d399" : "#a78bfa";
  return L.divIcon({
    className: "load-marker",
    html: `<div style="width:22px;height:22px;border-radius:6px;background:${color}22;border:1.5px solid ${color};display:flex;align-items:center;justify-content:center;font-size:12px">${isPickup ? emoji : "→"}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length < 2) return;
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
  }, [map, points]);
  return null;
}

interface Props {
  fleet: TruckSnapshot[];
  loads: LoadSnapshot[];
  plan: PlanAlternative | null;
  depot: { city: string; lat: number; lon: number };
}

export function DispatchMap({ fleet, loads, plan, depot }: Props) {
  const polylines = useMemo(() => {
    if (!plan) return [];
    const out: {
      color: string;
      positions: [number, number][];
      loaded: boolean;
      vanPlate: string;
    }[] = [];
    for (const p of plan.plans) {
      if (p.kind === "IDLE") continue;
      const color = vanColor(p.van_id);
      for (const leg of p.legs) {
        out.push({
          color,
          positions: [
            [leg.from_lat, leg.from_lon],
            [leg.to_lat, leg.to_lon],
          ],
          loaded: leg.kind === "loaded",
          vanPlate: p.van_plate,
        });
      }
    }
    return out;
  }, [plan]);

  const fitPoints = useMemo<[number, number][]>(() => {
    const pts: [number, number][] = [[depot.lat, depot.lon]];
    if (plan) {
      for (const p of plan.plans)
        for (const l of p.legs) {
          pts.push([l.from_lat, l.from_lon], [l.to_lat, l.to_lon]);
        }
    } else {
      for (const l of loads) pts.push([l.pickup_lat, l.pickup_lon]);
    }
    return pts;
  }, [plan, loads, depot.lat, depot.lon]);

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={[depot.lat, depot.lon]}
        zoom={7}
        className="h-full w-full"
        zoomControl
      >
        <TileLayer
          attribution='&copy; OpenStreetMap, &copy; CARTO'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        <FitBounds points={fitPoints} />

        <Marker position={[depot.lat, depot.lon]} icon={depotIcon}>
          <Popup>
            <strong>DEPOT — {depot.city}</strong>
            <br />
            {fleet.length} vans · home base
          </Popup>
        </Marker>

        {!plan &&
          loads.map((l) => (
            <Marker
              key={`pu-${l.load_id}`}
              position={[l.pickup_lat, l.pickup_lon]}
              icon={loadIcon(l, true)}
            >
              <Popup>
                <strong>{l.shipper_name}</strong>
                <br />
                {CARGO_EMOJI[l.cargo_type]} {l.cargo_description}
                <br />
                {l.pickup_city} → {l.delivery_city}
                <br />
                <strong>€{l.price_eur}</strong> · {l.weight_kg} kg · {l.source}
              </Popup>
            </Marker>
          ))}

        {!plan &&
          fleet.map((t) => (
            <Marker
              key={`v-${t.truck_id}`}
              position={[t.lat, t.lon]}
              icon={vanIcon(vanColor(t.truck_id), t.plate_number)}
            >
              <Popup>
                <strong>{t.plate_number}</strong>
                <br />
                {t.temp_capability}
                <br />
                Last cargo: {t.last_cargo ?? "—"}
                <br />
                Pharma logger: {t.has_pharma_logger ? "yes" : "no"}
              </Popup>
            </Marker>
          ))}

        {polylines.map((pl, i) => (
          <Polyline
            key={i}
            positions={pl.positions}
            pathOptions={{
              color: pl.color,
              weight: pl.loaded ? 4 : 2,
              opacity: pl.loaded ? 0.95 : 0.55,
              dashArray: pl.loaded ? undefined : "6 8",
              lineCap: "round",
            }}
          >
            <Popup>
              <strong>{pl.vanPlate}</strong>
              <br />
              {pl.loaded ? "Loaded leg" : "Empty leg"}
            </Popup>
          </Polyline>
        ))}
      </MapContainer>

      {/* Legend */}
      <div className="pointer-events-none absolute bottom-4 left-4 z-[400] rounded-lg border border-border bg-card/90 p-3 text-xs backdrop-blur">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Legend
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-base">★</span>
            <span>Depot — {depot.city}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-1 w-6 rounded bg-foreground" />
            <span>Loaded leg (paid km)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-px w-6 border-t border-dashed border-foreground" />
            <span>Empty leg (deadhead)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded bg-customer/70 border border-customer" />
            <span>Customer load</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded bg-broker/70 border border-broker" />
            <span>Broker load</span>
          </div>
        </div>
      </div>
    </div>
  );
}

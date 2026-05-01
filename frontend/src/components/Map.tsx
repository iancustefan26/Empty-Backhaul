import "leaflet/dist/leaflet.css";
import { MapContainer, Marker, Polyline, Popup, TileLayer } from "react-leaflet";

import { LoadFeature, TruckFeature } from "../types";
import { loadIcon, truckIcon } from "./icons";

interface Props {
  trucks: TruckFeature[];
  loads: LoadFeature[];
  selectedTruckId: number | null;
  chosenLoadId: number | null;
  onSelectTruck: (id: number) => void;
}

export function Map({
  trucks,
  loads,
  selectedTruckId,
  chosenLoadId,
  onSelectTruck,
}: Props) {
  const chosenLoad = loads.find((l) => l.id === chosenLoadId);
  const selectedTruck = trucks.find((t) => t.id === selectedTruckId);

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
              {p.current_city} → home {p.home_base_city}
              <br />
              capability: <code>{p.temp_capability}</code>
              <br />
              last cargo: <code>{p.last_cargo}</code>
              <br />
              status: <code>{p.status}</code>
              <br />
              <em>(click marker to run match)</em>
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
              <br />
              temp: {p.temp_min_celsius}/{p.temp_max_celsius} °C
              {p.requires_pharma_logger && (
                <>
                  <br />
                  <em>requires pharma logger</em>
                </>
              )}
            </Popup>
          </Marker>
        );
      })}

      {chosenLoad &&
        chosenLoad.geometry &&
        selectedTruck &&
        selectedTruck.geometry && (
          <>
            <Polyline
              positions={[
                [
                  selectedTruck.geometry.coordinates[1],
                  selectedTruck.geometry.coordinates[0],
                ],
                [
                  chosenLoad.geometry.coordinates[1],
                  chosenLoad.geometry.coordinates[0],
                ],
              ]}
              pathOptions={{
                color: "#6366f1",
                weight: 3,
                dashArray: "6 8",
                opacity: 0.85,
              }}
            />
            <Polyline
              positions={[
                [
                  chosenLoad.geometry.coordinates[1],
                  chosenLoad.geometry.coordinates[0],
                ],
                [
                  chosenLoad.properties.delivery_lat,
                  chosenLoad.properties.delivery_lon,
                ],
              ]}
              pathOptions={{ color: "#f59e0b", weight: 4, opacity: 0.9 }}
            />
          </>
        )}
    </MapContainer>
  );
}

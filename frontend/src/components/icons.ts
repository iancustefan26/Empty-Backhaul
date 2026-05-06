import L from "leaflet";

const TRUCK_COLORS: Record<string, string> = {
  empty: "#22c55e",
  loaded: "#eab308",
  returning: "#3b82f6",
  maintenance: "#6b7280",
};

const CARGO_EMOJI: Record<string, string> = {
  pharma: "💊",
  dairy: "🧀",
  produce: "🍎",
  raw_meat: "🥩",
  raw_poultry: "🍗",
  frozen_vegetables: "🥦",
  frozen_fish: "🐟",
  ambient_dry: "📦",
  chemicals: "⚗️",
};

const CARGO_COLORS: Record<string, string> = {
  pharma: "#dc2626",
  dairy: "#84cc16",
  produce: "#65a30d",
  raw_meat: "#991b1b",
  raw_poultry: "#a16207",
  frozen_vegetables: "#0891b2",
  frozen_fish: "#0e7490",
  ambient_dry: "#6b7280",
  chemicals: "#ea580c",
};

export function truckIcon(status: string, selected: boolean): L.DivIcon {
  const color = TRUCK_COLORS[status] ?? "#6b7280";
  const ringClass = selected ? "cbo-pulse" : "";
  const ringStyle = selected ? "box-shadow: 0 0 0 4px rgba(99,102,241,0.85);" : "";
  return L.divIcon({
    html: `<div class="${ringClass}" style="width:34px;height:34px;border-radius:50%;background:${color};
            display:flex;align-items:center;justify-content:center;color:white;
            font-size:18px;border:2px solid white;${ringStyle}cursor:pointer;">🚚</div>`,
    className: "cbo-truck-icon",
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

export function loadIcon(cargoType: string, chosen: boolean): L.DivIcon {
  const color = CARGO_COLORS[cargoType] ?? "#6b7280";
  const emoji = CARGO_EMOJI[cargoType] ?? "📦";
  const ring = chosen ? "box-shadow: 0 0 0 4px rgba(245,158,11,0.95);" : "";
  return L.divIcon({
    html: `<div style="width:26px;height:26px;border-radius:6px;background:${color};
            display:flex;align-items:center;justify-content:center;
            font-size:14px;border:2px solid white;${ring}">${emoji}</div>`,
    className: "cbo-load-icon",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

/** Big gold star marker for the company depot. */
export function depotIcon(): L.DivIcon {
  return L.divIcon({
    html: `<div style="position:relative;width:48px;height:48px;display:flex;align-items:center;justify-content:center;">
              <div style="position:absolute;width:48px;height:48px;border-radius:50%;background:rgba(250,204,21,0.25);"></div>
              <div style="position:relative;font-size:36px;line-height:1;color:#facc15;text-shadow:0 0 6px rgba(0,0,0,0.6);">★</div>
              <div style="position:absolute;bottom:-16px;left:50%;transform:translateX(-50%);font-size:10px;font-weight:700;color:#facc15;text-shadow:0 0 3px rgba(0,0,0,0.9);background:rgba(15,23,42,0.85);padding:1px 6px;border-radius:3px;border:1px solid #facc15;white-space:nowrap;">DEPOT</div>
            </div>`,
    className: "cbo-depot-icon",
    iconSize: [48, 48],
    iconAnchor: [24, 24],
  });
}

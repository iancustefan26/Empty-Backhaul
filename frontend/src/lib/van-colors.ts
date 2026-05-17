/**
 * Stable per-van colour palette + cargo emoji map.
 * Same colours as the previous Map.tsx so screenshots/docs stay consistent.
 */

export const VAN_PALETTE = [
  "#22d3ee", "#a78bfa", "#f59e0b", "#34d399", "#f472b6",
  "#60a5fa", "#fb7185", "#facc15", "#4ade80", "#c084fc",
  "#fda4af", "#fbbf24", "#84cc16", "#38bdf8", "#fb923c",
];

export function vanColor(vanId: number): string {
  return VAN_PALETTE[vanId % VAN_PALETTE.length];
}

/** Maps the dispatch-UI cargo enum to an emoji. */
export const CARGO_EMOJI: Record<string, string> = {
  pharma: "💊",
  dairy: "🧀",
  produce: "🥬",
  raw_meat: "🥩",
  raw_poultry: "🍗",
  frozen: "🥦",
  frozen_vegetables: "🥦",
  frozen_fish: "🐟",
  ambient_dry: "📦",
  general: "📦",
  chemicals: "⚗️",
};

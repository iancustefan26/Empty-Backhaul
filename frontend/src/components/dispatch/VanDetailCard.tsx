/**
 * Floating panel that opens when the dispatcher clicks a route polyline.
 * Designed to be glanceable, not a spreadsheet:
 *
 *   1. Header        — van plate + the cities visited
 *   2. Carrying      — one line per load (emoji + shipper + €) with phone
 *   3. Documents     — flat list of paperwork; status icon + doc name,
 *                      tap a row to read the regulatory citation
 *   4. Footer chip   — total km · driver hours · van's margin
 *
 * Pure absolute-positioned div over the map (NOT a Leaflet popup) so the
 * content can be rich React.
 */
import { Phone, X } from "lucide-react";
import { CARGO_EMOJI, vanColor } from "../../lib/van-colors";
import type {
  LoadSnapshot,
  PlanAlternative,
  TruckSnapshot,
} from "../../lib/dispatch-types";
import { requiredDocs, type DocStatus } from "../../lib/compliance-docs";

interface Props {
  vanId: number;
  plan: PlanAlternative | null;
  fleet: TruckSnapshot[];
  loads: LoadSnapshot[];
  onClose: () => void;
}

const STATUS: Record<
  DocStatus,
  { icon: string; color: string; label: string }
> = {
  ready: { icon: "✓", color: "text-good", label: "Ready" },
  warning: { icon: "!", color: "text-warn", label: "Verify" },
  missing: { icon: "✗", color: "text-destructive", label: "Missing" },
};

// Demo-only deterministic phone number per shipper.
function fakePhone(load: LoadSnapshot): string {
  const seed = load.load_id * 31 + load.shipper_name.length;
  const a = 700 + (seed % 100);
  const b = 100 + ((seed * 7) % 900);
  const c = 100 + ((seed * 13) % 900);
  return `+40 ${a} ${b} ${c}`;
}

export function VanDetailCard({ vanId, plan, fleet, loads, onClose }: Props) {
  const vanPlan = plan?.plans.find((p) => p.van_id === vanId);
  const truck = fleet.find((t) => t.truck_id === vanId);
  if (!vanPlan || !truck) return null;

  const cargoStops = vanPlan.legs
    .filter((l) => l.kind === "loaded" && l.load_id != null)
    .map((l) => loads.find((ld) => ld.load_id === l.load_id))
    .filter((l): l is LoadSnapshot => Boolean(l));

  const color = vanColor(vanId);
  const cities = [vanPlan.legs[0]?.from_city ?? "Cluj"]
    .concat(vanPlan.legs.map((l) => l.to_city))
    .filter((c, i, arr) => i === 0 || arr[i - 1] !== c);

  // De-duplicate documents across multiple loads (e.g. CMR appears for
  // every cargo) so the list is short and scannable.
  const allDocs = cargoStops.flatMap((load) => requiredDocs(load, truck));
  const seen = new Set<string>();
  const docs = allDocs.filter((d) => {
    const key = `${d.document}|${d.status}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div className="absolute right-3 top-3 z-[1000] w-[320px] max-h-[calc(100%-1.5rem)] overflow-hidden rounded-xl border border-border bg-card shadow-lg flex flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 shrink-0 rounded-full"
              style={{ background: color }}
            />
            <span
              className="font-mono text-sm font-semibold"
              style={{ color }}
            >
              {vanPlan.van_plate.replace("-CRL", "")}
            </span>
            {vanPlan.kind === "CHAIN" && (
              <span className="rounded bg-good/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-good">
                chain
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {cities.join(" → ")}
          </div>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-surface-1 hover:text-foreground"
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto thin-scroll px-4 py-3 space-y-4 text-sm">
        {/* Carrying */}
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Carrying
          </h3>
          <ul className="mt-2 space-y-2">
            {cargoStops.map((load, idx) => (
              <li
                key={`${load.load_id}-${idx}`}
                className="flex items-start gap-2"
              >
                <span className="text-lg leading-none">
                  {CARGO_EMOJI[load.cargo_type] ?? "📦"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate font-medium text-foreground">
                      {load.shipper_name}
                    </span>
                    <span className="shrink-0 font-semibold tabular-nums text-good">
                      €{load.price_eur}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground truncate">
                    {load.cargo_description}
                  </div>
                  <a
                    href={`tel:${fakePhone(load).replace(/\s/g, "")}`}
                    className="mt-0.5 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                  >
                    <Phone size={11} />
                    {fakePhone(load)}
                  </a>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Documents */}
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Documents to be legal
          </h3>
          <ul className="mt-2 space-y-1">
            {docs.map((doc, i) => {
              const s = STATUS[doc.status];
              return (
                <li key={`${doc.document}-${i}`}>
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md px-1.5 py-1 hover:bg-surface-1">
                      <span
                        className={`shrink-0 inline-flex h-4 w-4 items-center justify-center rounded-full text-[11px] font-bold ${s.color}`}
                        title={s.label}
                      >
                        {s.icon}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                        {doc.document}
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-foreground transition-transform group-open:rotate-90">
                        ▸
                      </span>
                    </summary>
                    <div className="ml-6 mt-1 space-y-0.5 text-[11px] leading-snug text-muted-foreground">
                      <div>{doc.why}</div>
                      {doc.detail && (
                        <div className="text-foreground/70 italic">
                          {doc.detail}
                        </div>
                      )}
                    </div>
                  </details>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      {/* Footer chip */}
      <div className="shrink-0 flex items-center justify-between border-t border-border bg-surface-1 px-4 py-2.5 text-xs">
        <span className="text-muted-foreground">
          {Math.round(vanPlan.total_km)} km · {vanPlan.drive_hours.toFixed(1)} h
        </span>
        <span className="font-semibold tabular-nums text-good">
          €{Math.round(vanPlan.margin_eur)} margin
        </span>
      </div>
    </div>
  );
}

/**
 * Per-plan detail panel — KPIs + per-van cards + alternatives switcher.
 * Rendered below the chat when an active plan exists.
 *
 * Ported from the Lovable bundle.
 */
import type {
  PlanAlternative,
  PlanResponse,
  VanPlan,
} from "../../lib/dispatch-types";
import { vanColor } from "../../lib/van-colors";
import { cn } from "../../lib/utils";

interface Props {
  plan: PlanResponse;
  activeRank: number;
  onSelectRank: (rank: number) => void;
}

function fmtEur(n: number) {
  return `€${n.toLocaleString("en-US")}`;
}

function KpiTile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "warn";
}) {
  return (
    <div className="rounded-md border border-border bg-surface-1 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-lg font-semibold tabular-nums",
          tone === "good" && "text-good",
          tone === "warn" && "text-warn",
        )}
      >
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function VanCard({ p }: { p: VanPlan }) {
  const color = vanColor(p.van_id);
  const route = [
    ...new Set([
      p.legs[0]?.from_city ?? "Depot",
      ...p.legs.map((l) => l.to_city),
    ]),
  ].join(" → ");
  return (
    <div className="rounded-md border border-border bg-surface-1 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: color }}
          />
          <span className="font-mono text-sm font-semibold" style={{ color }}>
            {p.van_plate}
          </span>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider",
              p.kind === "CHAIN"
                ? "bg-good/20 text-good"
                : "bg-muted text-muted-foreground",
            )}
          >
            {p.kind}
          </span>
        </div>
        <div className="text-sm font-semibold tabular-nums text-good">
          {fmtEur(p.margin_eur)}
        </div>
      </div>
      <div className="mt-1.5 truncate text-xs text-foreground/80">{route}</div>
      <div className="mt-1 flex gap-3 text-[11px] text-muted-foreground tabular-nums">
        <span>{p.total_km} km</span>
        <span>{p.drive_hours} h</span>
        <span>{Math.round((p.empty_km / Math.max(1, p.total_km)) * 100)}% empty</span>
      </div>
    </div>
  );
}

export function PlanDetail({ plan, activeRank, onSelectRank }: Props) {
  const alt: PlanAlternative =
    plan.optimiser.alternatives.find((a) => a.rank === activeRank) ??
    plan.optimiser.alternatives[0];
  if (!alt) return null;

  const active = alt.plans.filter((p) => p.kind !== "IDLE");
  const idle = alt.plans.filter((p) => p.kind === "IDLE");

  return (
    <div className="border-t border-border bg-card">
      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border bg-surface-1 px-3 py-2">
        {plan.optimiser.alternatives.map((a) => (
          <button
            key={a.rank}
            onClick={() => onSelectRank(a.rank)}
            className={cn(
              "rounded px-3 py-1.5 text-xs font-medium transition-colors",
              a.rank === activeRank
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface-2 hover:text-foreground",
            )}
          >
            Plan {a.rank} · {fmtEur(a.total_fleet_margin_eur)}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {plan.optimiser.optimiser_status} · {plan.optimiser.elapsed_ms} ms
        </span>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-3 gap-2 p-3">
        <KpiTile label="Margin" value={fmtEur(alt.total_fleet_margin_eur)} tone="good" />
        <KpiTile
          label="Deadhead"
          value={`${Math.round(alt.deadhead_ratio * 100)}%`}
          tone={alt.deadhead_ratio > 0.4 ? "warn" : undefined}
        />
        <KpiTile label="Utilisation" value={`${alt.fleet_utilization_pct}%`} />
        <KpiTile
          label="Customer SLA"
          value={`${alt.customer_loads_served}/${alt.customer_loads_available}`}
          tone={alt.unserved_customer_load_ids.length ? "warn" : "good"}
        />
        <KpiTile
          label="Broker captured"
          value={`${alt.broker_loads_served}/${alt.broker_loads_available}`}
        />
        <KpiTile label="Total km" value={alt.total_km.toLocaleString()} />
      </div>

      {/* Vans */}
      <div className="max-h-[36vh] overflow-y-auto thin-scroll px-3 pb-3 space-y-2">
        {active.map((p) => (
          <VanCard key={p.van_id} p={p} />
        ))}
        {idle.length > 0 && (
          <>
            <div className="pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Idle ({idle.length})
            </div>
            {idle.map((p) => (
              <div
                key={p.van_id}
                className="rounded-md border border-border bg-surface-1/50 px-3 py-2 text-xs text-muted-foreground flex items-center justify-between"
              >
                <span className="font-mono">{p.van_plate}</span>
                <span className="italic">no compatible profitable load</span>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

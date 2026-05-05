import { FleetMatchResponse, FleetPlanStats } from "../types";

interface Props {
  data: FleetMatchResponse | null;
  loading: boolean;
  error: string | null;
  selectedRank: number;
  onSelectRank: (rank: number) => void;
}

export function FleetView({
  data,
  loading,
  error,
  selectedRank,
  onSelectRank,
}: Props) {
  if (error) return <Box tone="error">Backend error: {error}</Box>;
  if (loading) return <Box tone="muted">Running fleet optimiser…</Box>;
  if (!data)
    return (
      <Box tone="muted">
        Click <span className="text-cyan-300">Run fleet match</span> in the
        header to dispatch the whole fleet at once.
      </Box>
    );

  const opt = data.optimiser;
  const sentry = data.sentry_log;
  const analyst = data.analyst_log;
  const plan = opt.alternatives.find((p) => p.rank === selectedRank) ?? opt.alternatives[0];

  if (!plan) {
    return (
      <Box tone="warn">
        Optimiser returned no plans. Status: <code>{opt.optimiser_status}</code>.
      </Box>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <Header sentry={sentry} analyst={analyst} opt={opt} />
      <AlternativesSwitcher
        alternatives={opt.alternatives}
        selectedRank={selectedRank}
        onSelect={onSelectRank}
      />
      <PlanStatsBlock plan={plan} />
      <PerTruckTable plan={plan} />
      {plan.unserved_customer_load_ids.length > 0 && (
        <Box tone="warn">
          <strong>SLA risk —</strong> {plan.unserved_customer_load_ids.length}{" "}
          customer load(s) unserved:{" "}
          {plan.unserved_customer_load_ids.map((id) => `L${id}`).join(", ")}
        </Box>
      )}
    </div>
  );
}

function Header({
  sentry,
  analyst,
  opt,
}: {
  sentry: FleetMatchResponse["sentry_log"];
  analyst: FleetMatchResponse["analyst_log"];
  opt: FleetMatchResponse["optimiser"];
}) {
  return (
    <div className="rounded border border-slate-700 bg-slate-800/50 p-3 text-xs">
      <div className="text-sm font-semibold text-slate-100">Fleet match</div>
      <div className="mt-1 text-slate-400">
        fleet={sentry.fleet_size} · loads={sentry.available_load_count} (
        {sentry.customer_loads} customer, {sentry.broker_loads} broker) ·
        candidate pairs={opt.candidate_pairs}
      </div>
      <div className="text-slate-400">
        analyst: {analyst.mode} · pre-blocked {analyst.pre_blocked_pairs}/
        {analyst.pair_count} · compliant {analyst.compliant_pairs} · {analyst.elapsed_ms}ms
        {analyst.sanity_corrections > 0 && (
          <span className="ml-1 text-amber-300">
            · {analyst.sanity_corrections} sanity-corrected
          </span>
        )}
      </div>
      <div className="text-slate-400">
        optimiser: {opt.optimiser_status} · {opt.alternatives.length} alternatives ·{" "}
        {opt.elapsed_ms}ms
      </div>
    </div>
  );
}

function AlternativesSwitcher({
  alternatives,
  selectedRank,
  onSelect,
}: {
  alternatives: FleetPlanStats[];
  selectedRank: number;
  onSelect: (rank: number) => void;
}) {
  if (alternatives.length === 0) return null;
  return (
    <div className="flex gap-1 text-xs">
      {alternatives.map((a) => (
        <button
          key={a.rank}
          className={
            "rounded border px-2 py-1 transition " +
            (a.rank === selectedRank
              ? "border-cyan-400 bg-cyan-900/40 text-cyan-100"
              : "border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500")
          }
          onClick={() => onSelect(a.rank)}
        >
          Plan {a.rank} · €{a.total_margin_eur.toFixed(0)}
        </button>
      ))}
    </div>
  );
}

function PlanStatsBlock({ plan }: { plan: FleetPlanStats }) {
  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      <Stat label="Total margin" value={`€${plan.total_margin_eur.toFixed(2)}`} accent="emerald" />
      <Stat
        label="Deadhead ratio"
        value={`${(plan.deadhead_ratio * 100).toFixed(1)}%`}
        accent={plan.deadhead_ratio > 0.2 ? "amber" : "emerald"}
      />
      <Stat
        label="Loaded km"
        value={`${plan.total_loaded_km.toFixed(0)} km`}
        accent="slate"
      />
      <Stat
        label="Empty km"
        value={`${plan.total_empty_km.toFixed(0)} km`}
        accent={plan.total_empty_km > 100 ? "amber" : "slate"}
      />
      <Stat
        label="Fleet utilisation"
        value={`${plan.fleet_utilization_pct.toFixed(0)}%`}
        accent="cyan"
      />
      <Stat
        label="Customer loads"
        value={`${plan.customer_loads_served} / ${plan.customer_loads_available}`}
        accent="emerald"
      />
      <Stat
        label="Broker loads"
        value={`${plan.broker_loads_served} / ${plan.broker_loads_available}`}
        accent="violet"
      />
      <Stat
        label="Total km"
        value={`${plan.total_km.toFixed(0)} km`}
        accent="slate"
      />
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "emerald" | "amber" | "cyan" | "violet" | "slate";
}) {
  const tones: Record<string, string> = {
    emerald: "border-emerald-700/40 text-emerald-300",
    amber: "border-amber-700/40 text-amber-300",
    cyan: "border-cyan-700/40 text-cyan-300",
    violet: "border-violet-700/40 text-violet-300",
    slate: "border-slate-700 text-slate-300",
  };
  return (
    <div className={`rounded border bg-slate-800/40 p-2 ${tones[accent]}`}>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="text-base font-semibold">{value}</div>
    </div>
  );
}

function PerTruckTable({ plan }: { plan: FleetPlanStats }) {
  return (
    <div className="overflow-x-auto rounded border border-slate-700">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-800 text-left text-slate-300">
          <tr>
            <th className="px-2 py-1">Truck</th>
            <th className="px-2 py-1">Load</th>
            <th className="px-2 py-1">Cargo</th>
            <th className="px-2 py-1">Route</th>
            <th className="px-2 py-1 text-right">Empty km</th>
            <th className="px-2 py-1 text-right">Loaded km</th>
            <th className="px-2 py-1 text-right">Margin €</th>
          </tr>
        </thead>
        <tbody>
          {plan.assignments.map((a) => (
            <tr
              key={a.truck_id}
              className={
                "border-t border-slate-800 " +
                (a.load_id === null ? "text-slate-500" : "")
              }
            >
              <td className="px-2 py-1 font-mono">{a.truck_plate}</td>
              <td className="px-2 py-1">
                {a.load_id !== null ? (
                  <span>
                    L{a.load_id}{" "}
                    <span
                      className={
                        a.source === "broker"
                          ? "text-violet-300"
                          : "text-emerald-300"
                      }
                    >
                      ·{a.source}
                    </span>
                  </span>
                ) : (
                  <span className="italic">idle</span>
                )}
              </td>
              <td className="px-2 py-1">
                {a.cargo_type ? <code>{a.cargo_type}</code> : "—"}
              </td>
              <td className="px-2 py-1">
                {a.load_pickup_city
                  ? `${a.load_pickup_city} → ${a.load_delivery_city}`
                  : a.truck_current_city}
              </td>
              <td className="px-2 py-1 text-right">{a.empty_km.toFixed(0)}</td>
              <td className="px-2 py-1 text-right">{a.loaded_km.toFixed(0)}</td>
              <td className="px-2 py-1 text-right">
                {a.load_id !== null ? a.margin_eur.toFixed(2) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Box({
  tone,
  children,
}: {
  tone: "muted" | "warn" | "error";
  children: React.ReactNode;
}) {
  const styles = {
    muted: "border-slate-700 bg-slate-800/30 text-slate-300",
    warn: "border-amber-700 bg-amber-950/40 text-amber-200",
    error: "border-red-700 bg-red-950/40 text-red-200",
  } as const;
  return (
    <div className={`m-3 rounded border p-3 text-xs ${styles[tone]}`}>{children}</div>
  );
}

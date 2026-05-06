import { DayPlan, RoutePlanResponse, RoutePlanStats } from "../types";

interface Props {
  data: RoutePlanResponse | null;
  loading: boolean;
  error: string | null;
  selectedRank: number;
  onSelectRank: (rank: number) => void;
  vanColors: Record<number, string>;
}

export function RouteView({
  data,
  loading,
  error,
  selectedRank,
  onSelectRank,
  vanColors,
}: Props) {
  if (error) return <Box tone="error">Backend error: {error}</Box>;
  if (loading) return <Box tone="muted">Planning today's routes…</Box>;
  if (!data) {
    return (
      <Box tone="muted">
        <div className="font-semibold">Cluj Reefer Logistics — daily routing</div>
        <div className="mt-2">
          Click <span className="text-cyan-300 font-semibold">Plan today's routes</span> to dispatch
          the fleet from the Cluj-Napoca depot.
        </div>
      </Box>
    );
  }

  const opt = data.optimiser;
  const sentry = data.sentry_log;
  const plan =
    opt.alternatives.find((p) => p.rank === selectedRank) ?? opt.alternatives[0];

  if (!plan) {
    return (
      <Box tone="warn">
        Optimiser returned no plan. Status: <code>{opt.optimiser_status}</code>.
      </Box>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <DepotHeader sentry={sentry} depot={data.depot} plan={plan} optElapsed={opt.elapsed_ms} />
      <AlternativesSwitcher
        alternatives={opt.alternatives}
        selectedRank={selectedRank}
        onSelect={onSelectRank}
      />
      <FleetKpis plan={plan} />
      <PerVanList plan={plan} vanColors={vanColors} />
      {plan.unserved_customer_load_ids.length > 0 && (
        <Box tone="warn">
          <strong>Customer SLA risk —</strong> {plan.unserved_customer_load_ids.length} customer
          load(s) not served today: {plan.unserved_customer_load_ids.map((id) => `L${id}`).join(", ")}
        </Box>
      )}
    </div>
  );
}

function DepotHeader({
  sentry,
  depot,
  plan,
  optElapsed,
}: {
  sentry: RoutePlanResponse["sentry_log"];
  depot: RoutePlanResponse["depot"];
  plan: RoutePlanStats;
  optElapsed: number;
}) {
  const dispatched = plan.single_trips_count + plan.chain_trips_count;
  return (
    <div className="rounded-lg border border-amber-700/40 bg-gradient-to-br from-amber-950/30 to-slate-900/60 p-3">
      <div className="flex items-center gap-2">
        <span className="text-2xl">⭐</span>
        <div>
          <div className="text-sm font-bold text-amber-200">
            Depot · {depot.city ?? "—"}
          </div>
          <div className="text-xs text-slate-400">
            {sentry.fleet_size} vans at base · {sentry.available_load_count} loads in pool (
            {sentry.customer_loads} customer, {sentry.broker_loads} broker)
          </div>
        </div>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded border border-emerald-700/40 bg-slate-800/60 p-2 text-center">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Dispatched</div>
          <div className="text-lg font-bold text-emerald-300">{dispatched}</div>
          <div className="text-[10px] text-slate-500">of {sentry.fleet_size}</div>
        </div>
        <div className="rounded border border-cyan-700/40 bg-slate-800/60 p-2 text-center">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Idle</div>
          <div className="text-lg font-bold text-slate-300">{plan.idle_count}</div>
          <div className="text-[10px] text-slate-500">at depot</div>
        </div>
        <div className="rounded border border-violet-700/40 bg-slate-800/60 p-2 text-center">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Plan time</div>
          <div className="text-lg font-bold text-violet-300">{optElapsed} ms</div>
          <div className="text-[10px] text-slate-500">CP-SAT</div>
        </div>
      </div>
    </div>
  );
}

function AlternativesSwitcher({
  alternatives,
  selectedRank,
  onSelect,
}: {
  alternatives: RoutePlanStats[];
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
            "flex-1 rounded border px-2 py-1.5 transition " +
            (a.rank === selectedRank
              ? "border-cyan-400 bg-cyan-900/40 text-cyan-100"
              : "border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500")
          }
          onClick={() => onSelect(a.rank)}
        >
          <div className="font-bold">Plan {a.rank}</div>
          <div className="text-[10px] text-slate-400">€{a.total_fleet_margin_eur.toFixed(0)} · {a.chain_trips_count} chain{a.chain_trips_count !== 1 ? "s" : ""}</div>
        </button>
      ))}
    </div>
  );
}

function FleetKpis({ plan }: { plan: RoutePlanStats }) {
  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      <Stat
        label="Total fleet profit"
        value={`€${plan.total_fleet_margin_eur.toFixed(2)}`}
        tone="emerald"
      />
      <Stat
        label="Deadhead"
        value={`${(plan.deadhead_ratio * 100).toFixed(1)}%`}
        tone={plan.deadhead_ratio > 0.4 ? "amber" : "emerald"}
      />
      <Stat
        label="Loaded km"
        value={`${plan.total_loaded_km.toFixed(0)} km`}
        tone="slate"
      />
      <Stat
        label="Empty km"
        value={`${plan.total_empty_km.toFixed(0)} km`}
        tone={plan.total_empty_km > plan.total_loaded_km ? "amber" : "slate"}
      />
      <Stat
        label="Customer loads"
        value={`${plan.customer_loads_served} / ${plan.customer_loads_available}`}
        tone="emerald"
      />
      <Stat
        label="Broker loads"
        value={`${plan.broker_loads_served} / ${plan.broker_loads_available}`}
        tone="violet"
      />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "emerald" | "amber" | "violet" | "slate";
}) {
  const tones: Record<string, string> = {
    emerald: "border-emerald-700/40 text-emerald-300",
    amber: "border-amber-700/40 text-amber-300",
    violet: "border-violet-700/40 text-violet-300",
    slate: "border-slate-700 text-slate-300",
  };
  return (
    <div className={`rounded border bg-slate-800/40 p-2 ${tones[tone]}`}>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-base font-semibold">{value}</div>
    </div>
  );
}

function PerVanList({
  plan,
  vanColors,
}: {
  plan: RoutePlanStats;
  vanColors: Record<number, string>;
}) {
  // Sort dispatched first (by margin DESC), then idle.
  const sorted = [...plan.plans].sort((a, b) => {
    if (a.kind === "IDLE" && b.kind !== "IDLE") return 1;
    if (a.kind !== "IDLE" && b.kind === "IDLE") return -1;
    return b.margin_eur - a.margin_eur;
  });
  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">
        Per-van plan
      </div>
      {sorted.map((p) => (
        <VanCard key={p.van_id} plan={p} colour={vanColors[p.van_id] ?? "#94a3b8"} />
      ))}
    </div>
  );
}

function VanCard({ plan, colour }: { plan: DayPlan; colour: string }) {
  if (plan.kind === "IDLE") {
    return (
      <div className="rounded border border-slate-800 bg-slate-900/50 p-2 text-xs text-slate-500">
        <span className="font-mono text-slate-400">{plan.van_plate}</span> · idle at depot
      </div>
    );
  }
  return (
    <div
      className="rounded border bg-slate-800/40 p-2 text-xs"
      style={{ borderLeft: `4px solid ${colour}` }}
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold" style={{ color: colour }}>
            {plan.van_plate}
          </span>
          <span
            className={
              "rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide " +
              (plan.kind === "CHAIN"
                ? "bg-violet-900/60 text-violet-100"
                : "bg-emerald-900/60 text-emerald-100")
            }
          >
            {plan.kind === "CHAIN" ? "chain" : "single"}
          </span>
        </div>
        <span className="font-semibold text-emerald-300">
          €{plan.margin_eur.toFixed(2)}
        </span>
      </div>
      <RouteSentence plan={plan} />
      <div className="mt-1 text-[10px] text-slate-500">
        {plan.total_km.toFixed(0)} km total · {plan.loaded_km.toFixed(0)} loaded ·{" "}
        {plan.empty_km.toFixed(0)} empty · {plan.drive_hours.toFixed(1)} h drive
      </div>
    </div>
  );
}

function RouteSentence({ plan }: { plan: DayPlan }) {
  // Collapse consecutive duplicate cities.
  const cities: string[] = [];
  for (const leg of plan.legs) {
    if (cities.length === 0 || cities[cities.length - 1] !== leg.from_city) {
      cities.push(leg.from_city);
    }
    cities.push(leg.to_city);
  }
  const collapsed: string[] = [];
  for (const c of cities) {
    if (collapsed.length === 0 || collapsed[collapsed.length - 1] !== c) collapsed.push(c);
  }
  return (
    <div className="mt-1 text-slate-300">
      {collapsed.map((c, i) => (
        <span key={`${c}-${i}`}>
          {i > 0 && <span className="mx-1 text-slate-500">→</span>}
          {c === "Cluj-Napoca" ? (
            <span className="font-semibold text-amber-200">{c}</span>
          ) : (
            c
          )}
        </span>
      ))}
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

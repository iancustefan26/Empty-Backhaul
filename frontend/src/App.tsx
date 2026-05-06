import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { fetchLoads, fetchTrucks, runMatch, runRoutePlan } from "./api";
import { FLEET_COLOURS, Map } from "./components/Map";
import { ReasoningFeed } from "./components/ReasoningFeed";
import { RouteView } from "./components/RouteView";
import { MatchState, RoutePlanResponse } from "./types";

type Mode = "route" | "single";

export function App() {
  const trucksQ = useQuery({ queryKey: ["trucks"], queryFn: fetchTrucks });
  const loadsQ = useQuery({ queryKey: ["loads"], queryFn: fetchLoads });

  const [mode, setMode] = useState<Mode>("route");

  // Route-plan state (the main product view)
  const [routeData, setRouteData] = useState<RoutePlanResponse | null>(null);
  const [routeRank, setRouteRank] = useState<number>(1);
  const [includeBroker, setIncludeBroker] = useState(true);
  const [enableChains, setEnableChains] = useState(true);

  const routeM = useMutation({
    mutationFn: () =>
      runRoutePlan({
        topK: 3,
        includeBroker,
        enableChains,
        mockLlm: true,
      }),
    onSuccess: (data) => {
      setRouteData(data);
      setRouteRank(1);
    },
  });

  // Single-truck (legacy) state
  const [selectedTruckId, setSelectedTruckId] = useState<number | null>(null);
  const [matchState, setMatchState] = useState<MatchState | null>(null);
  const matchM = useMutation({
    mutationFn: ({ id }: { id: number }) => runMatch(id, true),
    onSuccess: (data) => setMatchState(data),
  });

  const onSelectTruck = (id: number) => {
    if (mode !== "single") return;
    setSelectedTruckId(id);
    setMatchState(null);
    matchM.mutate({ id });
  };

  const trucks = trucksQ.data?.features ?? [];
  const loads = loadsQ.data?.features ?? [];
  const chosenLoadId = matchState?.decision?.chosen_load_id ?? null;

  // Stable color per van id, used both on the map and the side panel.
  const vanColors = useMemo(() => {
    const sorted = [...trucks].sort((a, b) => a.id - b.id);
    const m: Record<number, string> = {};
    sorted.forEach((t, i) => {
      m[t.id] = FLEET_COLOURS[i % FLEET_COLOURS.length];
    });
    return m;
  }, [trucks]);

  const routePlan =
    mode === "route" && routeData
      ? routeData.optimiser.alternatives.find((p) => p.rank === routeRank) ?? null
      : null;

  const depot = mode === "route" && routeData ? routeData.depot : null;

  return (
    <div className="flex h-screen w-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-700 bg-slate-900/95 px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🚚</span>
          <div>
            <div className="text-sm font-semibold text-slate-100">
              Cluj Reefer Logistics — daily dispatch
            </div>
            <div className="text-xs text-slate-400">
              Depot-based fleet planner · multi-leg backhauls · HACCP/ANSVSA/GDP compliant
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-300">
          <ModeTabs mode={mode} onChange={setMode} />
          <span>
            {trucks.length} vans · {loads.length} loads
          </span>
          {mode === "route" && (
            <>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={includeBroker}
                  onChange={(e) => setIncludeBroker(e.target.checked)}
                  className="accent-cyan-400"
                />
                broker freight
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={enableChains}
                  onChange={(e) => setEnableChains(e.target.checked)}
                  className="accent-cyan-400"
                />
                chains
              </label>
              <button
                className="rounded border border-cyan-700 bg-cyan-900/40 px-3 py-1.5 font-semibold text-cyan-100 hover:bg-cyan-800/60 disabled:opacity-50"
                disabled={routeM.isPending}
                onClick={() => routeM.mutate()}
              >
                {routeM.isPending ? "Planning…" : "Plan today's routes"}
              </button>
            </>
          )}
        </div>
      </header>

      <main className="grid flex-1 grid-cols-12 overflow-hidden">
        <section className="col-span-7 relative">
          {trucksQ.isError && (
            <BackendBanner message={(trucksQ.error as Error).message} />
          )}
          <Map
            trucks={trucks}
            loads={loads}
            selectedTruckId={selectedTruckId}
            chosenLoadId={chosenLoadId}
            onSelectTruck={onSelectTruck}
            routePlan={routePlan}
            depot={depot}
            vanColors={vanColors}
          />
          <Legend mode={mode} />
        </section>
        <aside className="col-span-5 overflow-y-auto border-l border-slate-700 bg-slate-900">
          {mode === "route" ? (
            <RouteView
              data={routeData}
              loading={routeM.isPending}
              error={routeM.isError ? (routeM.error as Error).message : null}
              selectedRank={routeRank}
              onSelectRank={setRouteRank}
              vanColors={vanColors}
            />
          ) : (
            <ReasoningFeed
              state={matchState}
              loading={matchM.isPending}
              error={matchM.isError ? (matchM.error as Error).message : null}
            />
          )}
        </aside>
      </main>
    </div>
  );
}

function ModeTabs({
  mode,
  onChange,
}: {
  mode: Mode;
  onChange: (m: Mode) => void;
}) {
  return (
    <div className="flex overflow-hidden rounded border border-slate-700">
      {(["route", "single"] as Mode[]).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={
            "px-2 py-1 text-xs " +
            (mode === m
              ? "bg-cyan-900/60 text-cyan-100"
              : "bg-slate-800 text-slate-400 hover:text-slate-200")
          }
        >
          {m === "route" ? "Daily routes" : "Single truck (debug)"}
        </button>
      ))}
    </div>
  );
}

function BackendBanner({ message }: { message: string }) {
  return (
    <div className="absolute left-1/2 top-3 z-[1000] -translate-x-1/2 rounded-md border border-red-700 bg-red-950/90 px-3 py-2 text-xs text-red-200 shadow-lg">
      <div className="font-semibold">Backend unreachable</div>
      <div>{message}</div>
      <div className="mt-1 text-red-300/80">
        Run <code>uvicorn app.main:app --reload</code> from <code>/backend</code>.
      </div>
    </div>
  );
}

function Legend({ mode }: { mode: Mode }) {
  return (
    <div className="absolute bottom-3 left-3 z-[400] space-y-1 rounded-md border border-slate-700 bg-slate-900/85 px-3 py-2 text-[11px] text-slate-300 shadow-lg">
      <div className="font-semibold text-slate-100">Legend</div>
      {mode === "route" && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-amber-300 text-base">★</span> Cluj depot
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block w-6 border-t-2 border-cyan-400" /> loaded leg ▲
          </div>
          <div className="flex items-center gap-2">
            <span
              className="inline-block w-6 border-t-2 border-dashed border-cyan-400/70"
              style={{ borderStyle: "dashed" }}
            />{" "}
            empty leg ▲ (arrows show direction)
          </div>
        </>
      )}
      <div className="flex items-center gap-2">
        <Square color="#dc2626" /> pharma
        <Square color="#84cc16" className="ml-2" /> dairy/produce
        <Square color="#0891b2" className="ml-2" /> frozen
        <Square color="#991b1b" className="ml-2" /> raw meat
      </div>
      <div className="flex items-center gap-2">
        <Square color="#ea580c" /> chemicals
        <Square color="#6b7280" className="ml-2" /> ambient
      </div>
    </div>
  );
}

function Square({
  color,
  className = "",
}: {
  color: string;
  className?: string;
}) {
  return (
    <span
      className={"inline-block h-3 w-3 rounded-sm border border-white " + className}
      style={{ background: color }}
    />
  );
}

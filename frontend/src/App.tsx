import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchLoads, fetchTrucks, runFleetMatch, runMatch } from "./api";
import { FleetView } from "./components/FleetView";
import { Map } from "./components/Map";
import { ReasoningFeed } from "./components/ReasoningFeed";
import { FleetMatchResponse, MatchState } from "./types";

type Mode = "single" | "fleet";

export function App() {
  const trucksQ = useQuery({ queryKey: ["trucks"], queryFn: fetchTrucks });
  const loadsQ = useQuery({ queryKey: ["loads"], queryFn: fetchLoads });

  const [mode, setMode] = useState<Mode>("single");

  // Single-truck state
  const [selectedTruckId, setSelectedTruckId] = useState<number | null>(null);
  const [matchState, setMatchState] = useState<MatchState | null>(null);
  const [useMockLlm, setUseMockLlm] = useState(true);

  const matchM = useMutation({
    mutationFn: ({ id, mock }: { id: number; mock: boolean }) =>
      runMatch(id, mock),
    onSuccess: (data) => setMatchState(data),
  });

  // Fleet state
  const [fleetData, setFleetData] = useState<FleetMatchResponse | null>(null);
  const [fleetRank, setFleetRank] = useState<number>(1);
  const [includeBroker, setIncludeBroker] = useState(true);

  const fleetM = useMutation({
    mutationFn: () =>
      runFleetMatch({ topK: 3, includeBroker, mockLlm: true }),
    onSuccess: (data) => {
      setFleetData(data);
      setFleetRank(1);
    },
  });

  const onSelectTruck = (id: number) => {
    if (mode !== "single") return;
    setSelectedTruckId(id);
    setMatchState(null);
    matchM.mutate({ id, mock: useMockLlm });
  };

  const trucks = trucksQ.data?.features ?? [];
  const loads = loadsQ.data?.features ?? [];
  const chosenLoadId = matchState?.decision?.chosen_load_id ?? null;
  const fleetPlan =
    mode === "fleet" && fleetData
      ? fleetData.optimiser.alternatives.find((p) => p.rank === fleetRank) ?? null
      : null;

  return (
    <div className="flex h-screen w-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-700 bg-slate-900/95 px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-xl">🚚</span>
          <div>
            <div className="text-sm font-semibold text-slate-100">
              Agentic Cold Backhaul Optimizer
            </div>
            <div className="text-xs text-slate-400">
              Romania · Sentry → Analyst → Strategist · LangGraph + Chroma RAG
              + OR-Tools
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-300">
          <ModeTabs mode={mode} onChange={setMode} />
          <span>
            {trucks.length} trucks · {loads.length} loads
          </span>
          {mode === "single" && (
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={useMockLlm}
                onChange={(e) => setUseMockLlm(e.target.checked)}
                className="accent-cyan-400"
              />
              mock LLM
            </label>
          )}
          {mode === "fleet" && (
            <>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={includeBroker}
                  onChange={(e) => setIncludeBroker(e.target.checked)}
                  className="accent-cyan-400"
                />
                include broker
              </label>
              <button
                className="rounded border border-cyan-700 bg-cyan-900/40 px-2 py-1 text-cyan-100 hover:bg-cyan-800/60 disabled:opacity-50"
                disabled={fleetM.isPending}
                onClick={() => fleetM.mutate()}
              >
                {fleetM.isPending ? "Optimising…" : "Run fleet match"}
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
            fleetPlan={fleetPlan}
          />
          <Legend />
        </section>
        <aside className="col-span-5 overflow-y-auto border-l border-slate-700 bg-slate-900">
          {mode === "single" ? (
            <ReasoningFeed
              state={matchState}
              loading={matchM.isPending}
              error={matchM.isError ? (matchM.error as Error).message : null}
            />
          ) : (
            <FleetView
              data={fleetData}
              loading={fleetM.isPending}
              error={fleetM.isError ? (fleetM.error as Error).message : null}
              selectedRank={fleetRank}
              onSelectRank={setFleetRank}
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
      {(["single", "fleet"] as Mode[]).map((m) => (
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
          {m === "single" ? "Single truck" : "Fleet"}
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

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 z-[400] space-y-1 rounded-md border border-slate-700 bg-slate-900/85 px-3 py-2 text-[11px] text-slate-300 shadow-lg">
      <div className="font-semibold text-slate-100">Legend</div>
      <div className="flex items-center gap-2">
        <Dot color="#22c55e" /> empty
        <Dot color="#eab308" className="ml-2" /> loaded
        <Dot color="#3b82f6" className="ml-2" /> returning
      </div>
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

function Dot({ color, className = "" }: { color: string; className?: string }) {
  return (
    <span
      className={"inline-block h-3 w-3 rounded-full border border-white " + className}
      style={{ background: color }}
    />
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

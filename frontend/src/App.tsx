/**
 * Cluj Reefer Logistics — Dispatcher Console.
 * One screen, two halves: a Romania map on the left, a chat assistant
 * on the right. Every interaction starts with natural language; the
 * assistant replies with a short sentence + an inline summary card.
 */
import { Truck } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";

import { ChatPanel } from "./components/dispatch/ChatPanel";
import {
  complianceSnapshot,
  explainIdleHeuristic,
  fetchPlan,
  type FetchPlanOptions,
} from "./lib/api-adapter";
import {
  clearHistory as clearStoredHistory,
  loadHistory,
  makeTurn,
  saveHistory,
} from "./lib/chat-store";
import { classify } from "./lib/nl-router";
import { computeStats, DIESEL_EUR_PER_LITRE } from "./lib/stats";
import type { ChatPayload, ChatTurn, PlanResponse } from "./lib/dispatch-types";
import { VanDetailCard } from "./components/dispatch/VanDetailCard";

// Leaflet only on the client — keep it out of the initial bundle.
const DispatchMap = lazy(() =>
  import("./components/dispatch/DispatchMap").then((m) => ({ default: m.DispatchMap })),
);

const DEFAULT_DEPOT = { city: "Cluj-Napoca", lat: 46.7712, lon: 23.6236 };

export function App() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [activePlan, setActivePlan] = useState<PlanResponse | null>(null);
  const [activeRank, setActiveRank] = useState<number>(1);
  const [mockLLM, setMockLLM] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVanId, setSelectedVanId] = useState<number | null>(null);

  // Restore from localStorage on first mount.
  useEffect(() => {
    const stored = loadHistory();
    setTurns(stored);
    for (let i = stored.length - 1; i >= 0; i--) {
      const p = stored[i].payload;
      if (p && p.kind === "plan") {
        setActivePlan(p.plan);
        setActiveRank(p.activeRank ?? 1);
        break;
      }
    }
  }, []);

  // Persist on every change.
  useEffect(() => {
    saveHistory(turns);
  }, [turns]);

  function pushTurn(
    role: "user" | "assistant",
    content: string,
    payload: ChatPayload | null = null,
  ) {
    const turn = makeTurn(role, content, payload);
    setTurns((t) => [...t, turn]);
  }

  async function handleSend(text: string) {
    pushTurn("user", text);
    setBusy(true);
    setError(null);
    try {
      const intent = classify(text);
      // Tiny artificial pause so single-call mock plans don't feel teleported.
      await new Promise((r) => setTimeout(r, 200));

      switch (intent.kind) {
        case "plan": {
          const opts: FetchPlanOptions = { ...intent.options, mockLlm: mockLLM };
          const plan = await fetchPlan(opts);
          const alt = plan.optimiser.alternatives[0];
          if (!alt) {
            pushTurn(
              "assistant",
              "The optimiser couldn't find a profitable plan with these constraints.",
            );
            break;
          }
          setActivePlan(plan);
          setActiveRank(1);
          setSelectedVanId(null);
          const alts = plan.optimiser.alternatives;
          const profits = alts
            .map((a) => `€${Math.round(a.total_fleet_margin_eur).toLocaleString()}`)
            .join(" · ");
          const slaWarn = alt.unserved_customer_load_ids.length
            ? ` ⚠ ${alt.unserved_customer_load_ids.length} customer load${alt.unserved_customer_load_ids.length > 1 ? "s" : ""} couldn't be served — review the SLA.`
            : "";
          const skipNote = intent.options.skip_cargo?.length
            ? ` (Skipping ${intent.options.skip_cargo.join(", ")} is a UX filter — backend wiring on the way.)`
            : "";
          const horizonNote = intent.options.horizon_days
            ? ` (For now I planned today only — multi-day will fan out across ${intent.options.horizon_days} days once the backend supports it.)`
            : "";
          const summary =
            alts.length > 1
              ? `Here is your plan for ${intent.humanLabel}. I prepared ${alts.length} options with different profits — ${profits}. Option 1 is the best by margin. Click any route on the map to see the shipper, cargo and compliance documents.${slaWarn}${skipNote}${horizonNote}`
              : `Here is your plan for ${intent.humanLabel} — €${Math.round(alt.total_fleet_margin_eur).toLocaleString()} total profit. Click any route on the map to see the shipper, cargo and compliance documents.${slaWarn}${skipNote}${horizonNote}`;
          pushTurn("assistant", summary, {
            kind: "plan",
            plan,
            options: intent.options,
            activeRank: 1,
          });
          break;
        }
        case "alternative": {
          if (!activePlan) {
            pushTurn(
              "assistant",
              "I don't have an active plan yet. Try 'Plan today's routes' first.",
            );
            break;
          }
          const alt = activePlan.optimiser.alternatives.find(
            (a) => a.rank === intent.rank,
          );
          if (!alt) {
            pushTurn(
              "assistant",
              `Plan ${intent.rank} doesn't exist — there are only ${activePlan.optimiser.alternatives.length} alternatives.`,
            );
            break;
          }
          setActiveRank(intent.rank);
          pushTurn(
            "assistant",
            `Switched to Plan ${intent.rank}: profit €${alt.total_fleet_margin_eur.toLocaleString()}, ${Math.round(alt.deadhead_ratio * 100)}% deadhead.`,
            { kind: "plan", plan: activePlan, options: {}, activeRank: intent.rank },
          );
          break;
        }
        case "idle_explain": {
          const reasons = explainIdleHeuristic(intent.van, activePlan);
          pushTurn("assistant", `Here's why ${intent.van} is idle:`, {
            kind: "idle_explain",
            van_plate: intent.van,
            reasons,
          });
          break;
        }
        case "compliance": {
          const c = complianceSnapshot();
          pushTurn(
            "assistant",
            `If we ignored compliance, we'd save dispatch time but risk €${c.saved_eur.toLocaleString()} in fines this week. Here's the breakdown:`,
            { kind: "compliance", saved_eur: c.saved_eur, violations: c.violations },
          );
          break;
        }
        case "stats": {
          if (!activePlan) {
            pushTurn(
              "assistant",
              "I don't have an active plan yet. Try 'Plan today's routes' first, then I can break down the costs.",
            );
            break;
          }
          const altForStats =
            activePlan.optimiser.alternatives.find((a) => a.rank === activeRank) ??
            activePlan.optimiser.alternatives[0];
          const s = computeStats(altForStats);
          pushTurn(
            "assistant",
            `Today's run is ${Math.round(s.total_km).toLocaleString()} km in total, of which ${Math.round(s.empty_km).toLocaleString()} km are empty (${s.empty_pct.toFixed(0)}%). At today's diesel price of €${DIESEL_EUR_PER_LITRE.toFixed(2)}/L, fuel alone is €${Math.round(s.fuel_cost_eur).toLocaleString()} — the full operating cost is €${Math.round(s.total_cost_eur).toLocaleString()}, leaving €${Math.round(s.margin_eur).toLocaleString()} margin.`,
            { kind: "stats", ...s },
          );
          break;
        }
        case "clarify": {
          pushTurn("assistant", intent.question, {
            kind: "clarify",
            suggestions: intent.suggestions,
          });
          break;
        }
        case "smalltalk": {
          pushTurn("assistant", intent.reply);
          break;
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      pushTurn("assistant", `Backend error: ${msg}`);
    } finally {
      setBusy(false);
    }
  }

  function handleClear() {
    clearStoredHistory();
    setTurns([]);
    setActivePlan(null);
    setSelectedVanId(null);
  }

  const activeAlt =
    activePlan?.optimiser.alternatives.find((a) => a.rank === activeRank) ??
    activePlan?.optimiser.alternatives[0] ??
    null;

  const depot = activePlan?.depot ?? DEFAULT_DEPOT;

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between border-b border-border bg-card px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Truck size={18} />
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight">
              Cluj Reefer Logistics
            </h1>
            <p className="text-xs text-muted-foreground">
              Cluj-Napoca depot
            </p>
          </div>
        </div>
        {/* Mock-LLM toggle as a subtle pill — only the dispatcher who
            cares will notice. Settings gear removed for now. */}
        <label className="flex cursor-pointer items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground select-none hover:border-primary/40">
          <input
            type="checkbox"
            checked={mockLLM}
            onChange={(e) => setMockLLM(e.target.checked)}
            className="h-3.5 w-3.5 accent-primary"
          />
          Use mock data (faster)
        </label>
      </header>

      {/* Body */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* Map */}
        <div className="relative h-1/2 min-h-0 flex-1 md:h-auto md:w-[60%]">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading map…
              </div>
            }
          >
            <DispatchMap
              fleet={activePlan?.fleet ?? []}
              loads={activePlan?.available_loads ?? []}
              plan={activeAlt}
              depot={depot}
              selectedVanId={selectedVanId}
              onSelectVan={setSelectedVanId}
            />
          </Suspense>
          {selectedVanId != null && activePlan && (
            <VanDetailCard
              vanId={selectedVanId}
              plan={activeAlt}
              fleet={activePlan.fleet}
              loads={activePlan.available_loads}
              onClose={() => setSelectedVanId(null)}
            />
          )}
          {error && (
            <div className="absolute left-1/2 top-3 z-[1000] -translate-x-1/2 rounded-md border border-destructive bg-card px-3 py-2 text-xs text-destructive shadow-lg">
              <div className="font-semibold">Backend error</div>
              <div className="text-foreground/80">{error}</div>
            </div>
          )}
        </div>

        {/* Right panel — chat only. The chat's own plan card carries
            the per-van details, so we no longer need a second panel. */}
        <aside className="flex h-1/2 min-h-0 flex-col border-l border-border bg-card md:h-auto md:w-[40%]">
          <ChatPanel
            turns={turns}
            busy={busy}
            onSend={handleSend}
            onClear={handleClear}
            onSelectAlt={(r) => setActiveRank(r)}
            activePlan={activePlan}
          />
        </aside>
      </div>
    </div>
  );
}

/**
 * FleetManager — modal for populating a custom test scenario.
 *
 * Two tabs:
 *   1. Trucks   — list + manual form + "Random N" button
 *   2. Loads    — list + manual form + "Random N" button
 *
 * Plus three workspace actions:
 *   - Reset (truncate everything)
 *   - Seed canonical (re-run the 25-van/100-load demo seed)
 *   - Close (X button)
 *
 * After any mutation the verdict cache is cleared server-side, so the
 * next "Plan today's routes" the user types in the chat re-evaluates.
 */
import { useEffect, useState } from "react";
import { Loader2, Plus, Trash2, X, Dice5, RefreshCw, Database, Globe } from "lucide-react";

import * as admin from "../../lib/admin-api";
import { cn } from "../../lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Called after any mutation that may have changed the planning input. */
  onDataChanged?: () => void;
}

type Tab = "trucks" | "loads";

export function FleetManager({ open, onClose, onDataChanged }: Props) {
  const [tab, setTab] = useState<Tab>("trucks");
  const [trucks, setTrucks] = useState<admin.TruckRow[]>([]);
  const [loads, setLoads] = useState<admin.LoadRow[]>([]);
  const [enums, setEnums] = useState<admin.AdminEnums | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Random counters
  const [truckRandomN, setTruckRandomN] = useState(5);
  const [loadRandomN, setLoadRandomN] = useState(10);
  const [cargo123N, setCargo123N] = useState(20);
  const [cargo123Info, setCargo123Info] = useState<admin.Cargo123Info | null>(null);

  // Manual-add form visibility
  const [addingTruck, setAddingTruck] = useState(false);
  const [addingLoad, setAddingLoad] = useState(false);

  useEffect(() => {
    if (!open) return;
    void refreshAll();
    if (!enums) void admin.fetchEnums().then(setEnums).catch((e) => setError(String(e)));
    // 404 is normal (no scraped dataset yet); swallow silently
    void admin.info123cargo().then(setCargo123Info).catch(() => setCargo123Info(null));
  }, [open]);

  async function refreshAll() {
    setLoading(true);
    setError(null);
    try {
      const [t, l] = await Promise.all([admin.listTrucks(), admin.listLoads()]);
      setTrucks(t);
      setLoads(l);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function withMutation(fn: () => Promise<void>) {
    setLoading(true);
    setError(null);
    try {
      await fn();
      await refreshAll();
      onDataChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // ----- workspace actions -----
  const handleReset = () => withMutation(async () => {
    if (!confirm("Truncate ALL trucks + loads + wash certs? This cannot be undone."))
      throw new Error("cancelled");
    await admin.resetWorkspace();
  });

  const handleReseedCanonical = () => withMutation(async () => {
    if (!confirm("Replace current data with the canonical 25-van / 100-load demo seed?"))
      throw new Error("cancelled");
    await admin.reseedCanonical();
  });

  // ----- truck actions -----
  const handleTruckRandom = () => withMutation(async () => {
    await admin.randomTrucks(truckRandomN);
  });
  const handleTruckDelete = (id: number) => withMutation(async () => {
    await admin.deleteTruck(id);
  });
  const handleTruckDeleteAll = () => withMutation(async () => {
    if (!confirm("Delete ALL trucks (and their wash certs)?"))
      throw new Error("cancelled");
    await admin.deleteAllTrucks();
  });

  // ----- load actions -----
  const handleLoadRandom = () => withMutation(async () => {
    await admin.randomLoads(loadRandomN);
  });
  const handleImport123cargo = () => withMutation(async () => {
    await admin.import123cargo(cargo123N, true);
    // Refresh dataset info too (it doesn't change, but for safety)
    const info = await admin.info123cargo().catch(() => null);
    setCargo123Info(info);
  });
  const handleLoadDelete = (id: number) => withMutation(async () => {
    await admin.deleteLoad(id);
  });
  const handleLoadDeleteAll = () => withMutation(async () => {
    if (!confirm("Delete ALL loads?"))
      throw new Error("cancelled");
    await admin.deleteAllLoads();
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-foreground/30 backdrop-blur-sm">
      <div className="relative flex h-[85vh] w-[min(1100px,95vw)] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-base font-semibold">Manage fleet &amp; loads</h2>
            <p className="text-xs text-muted-foreground">
              Build a custom test scenario, then go back to the chat and ask
              for a plan. Every change clears the verdict cache so the next
              plan re-evaluates from scratch.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-surface-1 hover:text-foreground"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tabs + workspace actions */}
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-5 py-2">
          <div className="flex gap-1">
            <TabButton active={tab === "trucks"} onClick={() => setTab("trucks")}>
              Trucks ({trucks.length})
            </TabButton>
            <TabButton active={tab === "loads"} onClick={() => setTab("loads")}>
              Loads ({loads.length})
            </TabButton>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <button
              onClick={() => void refreshAll()}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 hover:bg-surface-1"
              title="Reload from server"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <button
              onClick={handleReseedCanonical}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-foreground hover:bg-surface-1"
              title="Restore the 25-van / 100-load demo seed"
            >
              <Database size={12} />
              Seed canonical
            </button>
            <button
              onClick={handleReset}
              className="inline-flex items-center gap-1 rounded-md border border-destructive/40 px-2 py-1 text-destructive hover:bg-destructive/10"
              title="Wipe everything (trucks, loads, wash certs)"
            >
              <Trash2 size={12} />
              Reset all
            </button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="shrink-0 border-b border-destructive bg-destructive/10 px-5 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {/* Body */}
        <div className="flex flex-1 min-h-0 flex-col">
          {tab === "trucks" ? (
            <TrucksTab
              trucks={trucks}
              enums={enums}
              loading={loading}
              addingTruck={addingTruck}
              setAddingTruck={setAddingTruck}
              truckRandomN={truckRandomN}
              setTruckRandomN={setTruckRandomN}
              onRandom={handleTruckRandom}
              onDelete={handleTruckDelete}
              onDeleteAll={handleTruckDeleteAll}
              onAddSubmit={(body) =>
                withMutation(async () => {
                  await admin.createTruck(body);
                  setAddingTruck(false);
                })
              }
            />
          ) : (
            <LoadsTab
              loads={loads}
              enums={enums}
              loading={loading}
              addingLoad={addingLoad}
              setAddingLoad={setAddingLoad}
              loadRandomN={loadRandomN}
              setLoadRandomN={setLoadRandomN}
              cargo123Info={cargo123Info}
              cargo123N={cargo123N}
              setCargo123N={setCargo123N}
              onImport123cargo={handleImport123cargo}
              onRandom={handleLoadRandom}
              onDelete={handleLoadDelete}
              onDeleteAll={handleLoadDeleteAll}
              onAddSubmit={(body) =>
                withMutation(async () => {
                  await admin.createLoad(body);
                  setAddingLoad(false);
                })
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small subcomponents
// ---------------------------------------------------------------------------

function TabButton({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-surface-1 hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}

function RandomBar({ count, setCount, onAdd, loading, label }: {
  count: number; setCount: (n: number) => void; onAdd: () => void;
  loading: boolean; label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}:</span>
      <input
        type="number"
        min={1}
        max={100}
        value={count}
        onChange={(e) => setCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
        className="w-16 rounded-md border border-border bg-card px-2 py-1 text-sm tabular-nums"
      />
      <button
        onClick={onAdd}
        disabled={loading}
        className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Dice5 size={14} />}
        Add random
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trucks tab
// ---------------------------------------------------------------------------

function TrucksTab(props: {
  trucks: admin.TruckRow[];
  enums: admin.AdminEnums | null;
  loading: boolean;
  addingTruck: boolean;
  setAddingTruck: (b: boolean) => void;
  truckRandomN: number;
  setTruckRandomN: (n: number) => void;
  onRandom: () => void;
  onDelete: (id: number) => void;
  onDeleteAll: () => void;
  onAddSubmit: (body: admin.AdminTruckIn) => void;
}) {
  return (
    <>
      <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => props.setAddingTruck(!props.addingTruck)}
            className="inline-flex items-center gap-1 rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10"
          >
            <Plus size={14} />
            {props.addingTruck ? "Cancel" : "Add truck"}
          </button>
          {props.trucks.length > 0 && (
            <button
              onClick={props.onDeleteAll}
              className="inline-flex items-center gap-1 rounded-md border border-destructive/30 px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10"
            >
              <Trash2 size={12} /> Delete all
            </button>
          )}
        </div>
        <RandomBar
          count={props.truckRandomN}
          setCount={props.setTruckRandomN}
          onAdd={props.onRandom}
          loading={props.loading}
          label="How many random trucks"
        />
      </div>

      {props.addingTruck && props.enums && (
        <TruckForm enums={props.enums} onSubmit={props.onAddSubmit} />
      )}

      <div className="flex-1 min-h-0 overflow-y-auto thin-scroll">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-card text-xs uppercase text-muted-foreground">
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left">ID</th>
              <th className="px-3 py-2 text-left">Plate</th>
              <th className="px-3 py-2 text-left">Capability</th>
              <th className="px-3 py-2 text-left">Last cargo</th>
              <th className="px-3 py-2 text-left">Logger</th>
              <th className="px-3 py-2 text-left">City</th>
              <th className="px-3 py-2 text-right">Hours</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {props.trucks.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-12 text-center text-muted-foreground">
                No trucks. Click "Add truck" or "Add random" above.
              </td></tr>
            )}
            {props.trucks.map((t) => (
              <tr key={t.id} className="border-b border-border/40 hover:bg-surface-1">
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{t.id}</td>
                <td className="px-3 py-2 font-mono text-xs">{t.plate_number}</td>
                <td className="px-3 py-2">{t.temp_capability}</td>
                <td className="px-3 py-2">{t.last_cargo}</td>
                <td className="px-3 py-2">{t.has_pharma_logger ? "yes" : "—"}</td>
                <td className="px-3 py-2">{t.current_city}</td>
                <td className="px-3 py-2 text-right tabular-nums">{t.remaining_driving_hours.toFixed(1)} h</td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => props.onDelete(t.id)}
                    className="rounded-md p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Delete truck"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function TruckForm({ enums, onSubmit }: {
  enums: admin.AdminEnums;
  onSubmit: (body: admin.AdminTruckIn) => void;
}) {
  const [body, setBody] = useState<admin.AdminTruckIn>({
    plate_number: "",
    temp_capability: enums.truck_capabilities[0],
    last_cargo: enums.truck_last_cargoes[0],
    has_pharma_logger: false,
    current_city: enums.cities.includes("Cluj-Napoca") ? "Cluj-Napoca" : enums.cities[0],
    home_base_city: enums.cities.includes("Cluj-Napoca") ? "Cluj-Napoca" : enums.cities[0],
  });

  return (
    <div className="shrink-0 border-b border-border bg-surface-1 p-4">
      <form
        onSubmit={(e) => { e.preventDefault(); onSubmit(body); }}
        className="grid grid-cols-1 gap-3 md:grid-cols-3"
      >
        <FormField label="Plate number">
          <input
            required
            type="text"
            value={body.plate_number}
            placeholder="CJ-123-CRL"
            onChange={(e) => setBody({ ...body, plate_number: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          />
        </FormField>
        <FormField label="Temperature capability">
          <select
            value={body.temp_capability}
            onChange={(e) => setBody({ ...body, temp_capability: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.truck_capabilities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
        <FormField label="Last cargo">
          <select
            value={body.last_cargo}
            onChange={(e) => setBody({ ...body, last_cargo: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.truck_last_cargoes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
        <FormField label="Current city">
          <select
            value={body.current_city}
            onChange={(e) => setBody({ ...body, current_city: e.target.value, home_base_city: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.cities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
        <FormField label="Pharma logger">
          <label className="flex items-center gap-2 py-1.5 text-sm">
            <input
              type="checkbox"
              checked={body.has_pharma_logger}
              onChange={(e) => setBody({ ...body, has_pharma_logger: e.target.checked })}
            />
            On board (calibrated)
          </label>
        </FormField>
        <FormField label="Remaining driving hours">
          <input
            type="number"
            min={1}
            max={12}
            step={0.5}
            value={body.remaining_driving_hours ?? 9}
            onChange={(e) => setBody({ ...body, remaining_driving_hours: parseFloat(e.target.value) })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          />
        </FormField>
        <div className="md:col-span-3 flex justify-end gap-2">
          <button
            type="submit"
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Save truck
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loads tab
// ---------------------------------------------------------------------------

function LoadsTab(props: {
  loads: admin.LoadRow[];
  enums: admin.AdminEnums | null;
  loading: boolean;
  addingLoad: boolean;
  setAddingLoad: (b: boolean) => void;
  loadRandomN: number;
  setLoadRandomN: (n: number) => void;
  cargo123Info: admin.Cargo123Info | null;
  cargo123N: number;
  setCargo123N: (n: number) => void;
  onImport123cargo: () => void;
  onRandom: () => void;
  onDelete: (id: number) => void;
  onDeleteAll: () => void;
  onAddSubmit: (body: admin.AdminLoadIn) => void;
}) {
  const has123 = props.cargo123Info?.exists && (props.cargo123Info?.available ?? 0) > 0;
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-border px-5 py-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={() => props.setAddingLoad(!props.addingLoad)}
              className="inline-flex items-center gap-1 rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10"
            >
              <Plus size={14} />
              {props.addingLoad ? "Cancel" : "Add load"}
            </button>
            {props.loads.length > 0 && (
              <button
                onClick={props.onDeleteAll}
                className="inline-flex items-center gap-1 rounded-md border border-destructive/30 px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10"
              >
                <Trash2 size={12} /> Delete all
              </button>
            )}
          </div>
          <RandomBar
            count={props.loadRandomN}
            setCount={props.setLoadRandomN}
            onAdd={props.onRandom}
            loading={props.loading}
            label="How many random loads"
          />
        </div>

        {/* 123cargo dataset row */}
        {has123 && (
          <div className="flex items-center justify-between rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-xs">
            <div className="flex items-center gap-2">
              <Globe size={14} className="text-accent" />
              <span>
                <strong>123cargo Frigo dataset</strong> · {props.cargo123Info!.available} real loads scraped
                {props.cargo123Info?.scraped_at_utc && (
                  <span className="text-muted-foreground">
                    {" "}({new Date(props.cargo123Info.scraped_at_utc).toLocaleString()})
                  </span>
                )}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Import:</span>
              <input
                type="number"
                min={1}
                max={Math.min(500, props.cargo123Info?.available ?? 500)}
                value={props.cargo123N}
                onChange={(e) => props.setCargo123N(Math.max(1, Math.min(500, parseInt(e.target.value) || 1)))}
                className="w-16 rounded-md border border-border bg-card px-2 py-1 text-sm tabular-nums"
              />
              <button
                onClick={props.onImport123cargo}
                disabled={props.loading}
                className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {props.loading ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
                Load from 123cargo
              </button>
            </div>
          </div>
        )}
      </div>

      {props.addingLoad && props.enums && (
        <LoadForm enums={props.enums} onSubmit={props.onAddSubmit} />
      )}

      <div className="flex-1 min-h-0 overflow-y-auto thin-scroll">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-card text-xs uppercase text-muted-foreground">
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left">ID</th>
              <th className="px-3 py-2 text-left">Cargo</th>
              <th className="px-3 py-2 text-left">Route</th>
              <th className="px-3 py-2 text-right">Weight</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-left">Source</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {props.loads.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-12 text-center text-muted-foreground">
                No loads. Click "Add load" or "Add random" above.
              </td></tr>
            )}
            {props.loads.map((l) => (
              <tr key={l.id} className="border-b border-border/40 hover:bg-surface-1">
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{l.id}</td>
                <td className="px-3 py-2">{l.cargo_type}</td>
                <td className="px-3 py-2">{l.pickup_city} → {l.delivery_city}</td>
                <td className="px-3 py-2 text-right tabular-nums">{(l.weight_kg / 1000).toFixed(1)} t</td>
                <td className="px-3 py-2 text-right tabular-nums font-medium text-good">€{l.price_eur.toFixed(0)}</td>
                <td className="px-3 py-2">{l.source}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => props.onDelete(l.id)}
                    className="rounded-md p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Delete load"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const CARGO_DEFAULTS: Record<string, { temp: [number, number]; logger: boolean; fpc: string | null }> = {
  pharma:            { temp: [2, 8],     logger: true,  fpc: "chemicals,raw_meat,raw_poultry" },
  dairy:             { temp: [2, 7],     logger: false, fpc: "raw_meat,raw_poultry,chemicals" },
  produce:           { temp: [4, 10],    logger: false, fpc: "raw_meat,raw_poultry,chemicals" },
  raw_meat:          { temp: [0, 4],     logger: false, fpc: "chemicals" },
  raw_poultry:       { temp: [0, 4],     logger: false, fpc: "chemicals" },
  frozen_vegetables: { temp: [-25, -18], logger: false, fpc: null },
  frozen_fish:       { temp: [-22, -18], logger: false, fpc: "chemicals" },
  ambient_dry:       { temp: [5, 25],    logger: false, fpc: "chemicals" },
  chemicals:         { temp: [5, 30],    logger: false, fpc: null },
};

function LoadForm({ enums, onSubmit }: {
  enums: admin.AdminEnums;
  onSubmit: (body: admin.AdminLoadIn) => void;
}) {
  // Default window: pickup in 2-8h from now, 8h wide
  const now = new Date();
  now.setHours(now.getHours() + 2, 0, 0, 0);
  const startDefault = now.toISOString().slice(0, 16);
  const endDate = new Date(now.getTime() + 8 * 3600 * 1000);
  const endDefault = endDate.toISOString().slice(0, 16);

  const cluj = enums.cities.includes("Cluj-Napoca") ? "Cluj-Napoca" : enums.cities[0];
  const brasov = enums.cities.includes("Brasov") ? "Brasov" : enums.cities[1] ?? enums.cities[0];
  const defaults = CARGO_DEFAULTS.pharma;

  const [body, setBody] = useState<admin.AdminLoadIn>({
    shipper_name: "",
    cargo_type: "pharma",
    cargo_description: "",
    temp_min_celsius: defaults.temp[0],
    temp_max_celsius: defaults.temp[1],
    requires_pharma_logger: defaults.logger,
    forbidden_prior_cargo: defaults.fpc,
    pickup_city: cluj,
    delivery_city: brasov,
    pickup_window_start: startDefault + ":00.000Z",
    pickup_window_end: endDefault + ":00.000Z",
    weight_kg: 5000,
    price_eur: 500,
    source: "customer",
  });

  function changeCargo(cargo: string) {
    const d = CARGO_DEFAULTS[cargo] ?? { temp: [0, 25] as [number, number], logger: false, fpc: null };
    setBody({
      ...body,
      cargo_type: cargo,
      temp_min_celsius: d.temp[0],
      temp_max_celsius: d.temp[1],
      requires_pharma_logger: d.logger,
      forbidden_prior_cargo: d.fpc,
    });
  }

  return (
    <div className="shrink-0 border-b border-border bg-surface-1 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          // Normalise datetime-local (no Z) to UTC ISO string
          onSubmit({
            ...body,
            pickup_window_start: new Date(body.pickup_window_start).toISOString(),
            pickup_window_end: new Date(body.pickup_window_end).toISOString(),
          });
        }}
        className="grid grid-cols-1 gap-3 md:grid-cols-3"
      >
        <FormField label="Shipper name (optional)">
          <input
            type="text"
            value={body.shipper_name ?? ""}
            placeholder="Antibiotice Iași"
            onChange={(e) => setBody({ ...body, shipper_name: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          />
        </FormField>
        <FormField label="Cargo type">
          <select
            value={body.cargo_type}
            onChange={(e) => changeCargo(e.target.value)}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.cargo_types.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
        <FormField label="Source">
          <select
            value={body.source}
            onChange={(e) => setBody({ ...body, source: e.target.value as "customer" | "broker" })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.load_sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </FormField>
        <FormField label="Pickup city">
          <select
            value={body.pickup_city}
            onChange={(e) => setBody({ ...body, pickup_city: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.cities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
        <FormField label="Delivery city">
          <select
            value={body.delivery_city}
            onChange={(e) => setBody({ ...body, delivery_city: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          >
            {enums.cities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
        <FormField label="Weight (kg)">
          <input
            type="number"
            min={1}
            max={40000}
            value={body.weight_kg}
            onChange={(e) => setBody({ ...body, weight_kg: parseInt(e.target.value) || 0 })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm tabular-nums"
          />
        </FormField>
        <FormField label="Price (€)">
          <input
            type="number"
            min={0}
            max={100000}
            value={body.price_eur}
            onChange={(e) => setBody({ ...body, price_eur: parseFloat(e.target.value) || 0 })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm tabular-nums"
          />
        </FormField>
        <FormField label="Temp min (°C)">
          <input
            type="number"
            step={0.5}
            value={body.temp_min_celsius}
            onChange={(e) => setBody({ ...body, temp_min_celsius: parseFloat(e.target.value) || 0 })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm tabular-nums"
          />
        </FormField>
        <FormField label="Temp max (°C)">
          <input
            type="number"
            step={0.5}
            value={body.temp_max_celsius}
            onChange={(e) => setBody({ ...body, temp_max_celsius: parseFloat(e.target.value) || 0 })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm tabular-nums"
          />
        </FormField>
        <FormField label="Pickup window start">
          <input
            type="datetime-local"
            value={body.pickup_window_start.slice(0, 16)}
            onChange={(e) => setBody({ ...body, pickup_window_start: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          />
        </FormField>
        <FormField label="Pickup window end">
          <input
            type="datetime-local"
            value={body.pickup_window_end.slice(0, 16)}
            onChange={(e) => setBody({ ...body, pickup_window_end: e.target.value })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          />
        </FormField>
        <FormField label="Forbidden prior cargo (comma-sep, blank = none)">
          <input
            type="text"
            value={body.forbidden_prior_cargo ?? ""}
            placeholder="raw_meat,chemicals"
            onChange={(e) => setBody({
              ...body,
              forbidden_prior_cargo: e.target.value.trim() ? e.target.value : null,
            })}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
          />
        </FormField>
        <div className="md:col-span-3 flex justify-end gap-2">
          <button
            type="submit"
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Save load
          </button>
        </div>
      </form>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

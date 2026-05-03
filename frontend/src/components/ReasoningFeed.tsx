import { Fragment } from "react";

import { MatchState } from "../types";

interface Props {
  state: MatchState | null;
  loading: boolean;
  error: string | null;
}

export function ReasoningFeed({ state, loading, error }: Props) {
  if (error) {
    return (
      <div className="m-4 rounded-lg border border-red-700 bg-red-950/50 p-4 text-sm text-red-200">
        <div className="font-semibold">Match failed</div>
        <div>{error}</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="m-4 rounded-lg border border-slate-700 bg-slate-800/60 p-4 text-sm text-slate-300">
        <div className="flex items-center gap-2">
          <div className="h-3 w-3 animate-pulse rounded-full bg-cyan-400" />
          Running Sentry → Analyst → Strategist…
        </div>
        <div className="mt-2 text-xs text-slate-500">
          Per-load Chroma retrieval × 20 typically takes 10–25 s in mock mode.
        </div>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="m-4 rounded-lg border border-dashed border-slate-700 bg-slate-800/30 p-6 text-sm text-slate-400">
        <div className="text-base font-semibold text-slate-200">
          Pick a truck to start
        </div>
        <div className="mt-2">
          Click any truck marker on the map. The Sentry hydrates its profile,
          the Analyst runs a RAG-backed compliance check on every available
          load, and the Strategist runs an OR-Tools optimisation to pick the
          most profitable compliant backhaul.
        </div>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="m-4 rounded-lg border border-amber-700 bg-amber-950/50 p-4 text-sm text-amber-200">
        <div className="font-semibold">Workflow halted</div>
        <div>{state.error}</div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      <SentryCard state={state} />
      <AnalystCard state={state} />
      <StrategistCard state={state} />
      <DocumentsCard state={state} />
    </div>
  );
}

// ---------- 1. Sentry ----------

function SentryCard({ state }: { state: MatchState }) {
  const t = state.truck;
  const log = state.sentry_log;
  return (
    <Card accent="border-sentry/60" badge="1" badgeColor="bg-sentry">
      <CardTitle>Sentry — Truck profile</CardTitle>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <Field label="Plate">
          {t.plate_number} <span className="text-slate-500">({t.carrier_name})</span>
        </Field>
        <Field label="Status">
          <Pill className={statusPillClass(t.status)}>{t.status}</Pill>
        </Field>
        <Field label="Currently in">{t.current_city}</Field>
        <Field label="Home base">{t.home_base_city}</Field>
        <Field label="Capability">
          <code>{t.temp_capability}</code>
        </Field>
        <Field label="Last cargo">
          <code>{t.last_cargo}</code>
        </Field>
        <Field label="Pharma logger">
          {t.has_pharma_logger ? "✓ calibrated" : "—"}
        </Field>
        <Field label="Driving hours left">{t.remaining_driving_hours} h</Field>
      </div>
      <div className="mt-3 text-xs text-slate-400">
        Wash certificates on file:{" "}
        <span className="text-slate-200">{log.wash_certificate_count}</span>{" "}
        (currently valid:{" "}
        <span className="text-slate-200">{log.valid_wash_certificate_count}</span>) ·
        Available loads:{" "}
        <span className="text-slate-200">{log.available_load_count}</span> ·
        observed at {formatTime(log.monitored_at)}
      </div>
      {t.wash_certificates.length > 0 && (
        <div className="mt-2 space-y-1 text-xs">
          {t.wash_certificates.map((w) => (
            <div
              key={w.certificate_number}
              className={
                "rounded border px-2 py-1 " +
                (w.is_currently_valid
                  ? "border-emerald-700 bg-emerald-950/40"
                  : "border-slate-700 bg-slate-800/60 text-slate-400")
              }
            >
              <span className="font-mono text-emerald-300">
                {w.certificate_number}
              </span>{" "}
              · type=<code>{w.wash_type}</code> · after{" "}
              <code>{w.prior_cargo}</code> ·{" "}
              {w.is_currently_valid ? "valid" : "expired"} until{" "}
              {formatTime(w.valid_until)}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ---------- 2. Analyst ----------

function AnalystCard({ state }: { state: MatchState }) {
  const log = state.analyst_log;
  const loads = Object.fromEntries(state.available_loads.map((l) => [l.id, l]));
  const verdicts = state.compliance_results;
  return (
    <Card accent="border-analyst/60" badge="2" badgeColor="bg-analyst">
      <CardTitle>Analyst — RAG-backed compliance</CardTitle>
      <div className="mt-1 text-xs text-slate-400">
        mode=<code>{log.mode}</code>
        {log.model && (
          <>
            {" "}
            · model=<code>{log.model}</code>
          </>
        )}{" "}
        · evaluated {log.evaluated_loads} · compliant{" "}
        <span className="text-emerald-300">{log.compliant_count}</span> ·{" "}
        {log.rag_hits} rule-hits
        {typeof log.corpus_hits === "number" && (
          <> · {log.corpus_hits} corpus-hits</>
        )}
        {typeof log.cache_hits === "number" && log.cache_hits > 0 && (
          <> · {log.cache_hits} cached</>
        )}
        {typeof log.sanity_overrides_count === "number" &&
          log.sanity_overrides_count > 0 && (
            <>
              {" "}
              ·{" "}
              <span className="text-amber-300">
                {log.sanity_overrides_count} sanity-corrected
              </span>
            </>
          )}{" "}
        · {log.elapsed_ms} ms
      </div>
      <div className="mt-3 max-h-72 overflow-auto rounded border border-slate-700">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-slate-800 text-left text-slate-300">
            <tr>
              <th className="px-2 py-1">#</th>
              <th className="px-2 py-1">Cargo</th>
              <th className="px-2 py-1">Route</th>
              <th className="px-2 py-1 text-center">Verdict</th>
              <th className="px-2 py-1">Reason / blocker</th>
            </tr>
          </thead>
          <tbody>
            {verdicts.map((v) => {
              const ld = loads[v.load_id];
              const reason =
                v.blockers[0] ??
                v.warnings[0] ??
                (v.reasoning.length > 90 ? v.reasoning.slice(0, 90) + "…" : v.reasoning);
              const excerpts = v.cited_excerpts ?? [];
              return (
                <Fragment key={v.load_id}>
                  <tr
                    className={
                      "border-t border-slate-800 " +
                      (v.is_compliant ? "" : "text-slate-400")
                    }
                  >
                    <td className="px-2 py-1 font-mono">{ld?.id}</td>
                    <td className="px-2 py-1">
                      <code>{ld?.cargo_type}</code>
                    </td>
                    <td className="px-2 py-1">
                      {ld?.pickup_city} → {ld?.delivery_city}
                    </td>
                    <td className="px-2 py-1 text-center">
                      {v.is_compliant ? (
                        <span className="rounded bg-emerald-700/40 px-1.5 py-0.5 text-emerald-200">
                          ✓ ok
                        </span>
                      ) : (
                        <span className="rounded bg-red-900/40 px-1.5 py-0.5 text-red-300">
                          ✗ block
                        </span>
                      )}
                      {v.sanity_overrides && v.sanity_overrides.length > 0 && (
                        <span
                          className="ml-1 rounded border border-amber-700 bg-amber-950/40 px-1.5 py-0.5 text-[10px] text-amber-300"
                          title={`Deterministic sanity layer corrected the LLM verdict. Rules enforced: ${v.sanity_overrides.join(
                            ", ",
                          )}`}
                        >
                          auto-corrected
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1 text-slate-300">{reason}</td>
                  </tr>
                  {excerpts.length > 0 && (
                    <tr className="border-t border-slate-900/60 bg-slate-900/40">
                      <td className="px-2 py-1" />
                      <td colSpan={4} className="px-2 py-1">
                        <details>
                          <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-analyst/80 hover:text-analyst">
                            Sources ({excerpts.length})
                          </summary>
                          <ul className="mt-1 space-y-1.5">
                            {excerpts.map((e, i) => (
                              <li
                                key={`${v.load_id}-${e.source_id}-${i}`}
                                className="border-l-2 border-analyst/40 pl-2"
                              >
                                <div className="text-[11px] text-slate-400">
                                  <span className="text-analyst">{e.citation}</span>
                                  <span className="ml-1 opacity-60">
                                    [{e.language}] · cosine {e.distance.toFixed(2)}
                                  </span>
                                </div>
                                <div className="text-xs italic text-slate-300">
                                  “{e.snippet}”
                                </div>
                              </li>
                            ))}
                          </ul>
                        </details>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ---------- 3. Strategist ----------

function StrategistCard({ state }: { state: MatchState }) {
  const d = state.decision;
  return (
    <Card accent="border-strategist/60" badge="3" badgeColor="bg-strategist">
      <CardTitle>Strategist — OR-Tools selection</CardTitle>
      <div className="mt-1 text-xs text-slate-400">
        optimiser status: <code>{d.optimiser_status}</code>
      </div>
      {d.chosen_load_id == null ? (
        <div className="mt-3 rounded border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-200">
          {d.explanation}
        </div>
      ) : (
        <>
          <div className="mt-3 rounded border border-strategist/60 bg-strategist/10 p-3">
            <div className="text-xs uppercase text-strategist">Chosen load</div>
            <div className="mt-1 text-base font-semibold">
              #{d.chosen_load_id} · <code>{d.chosen_load!.cargo_type}</code> ·{" "}
              {d.chosen_load!.pickup_city} → {d.chosen_load!.delivery_city}
            </div>
            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <Field label="Empty deadhead">{d.empty_detour_km} km</Field>
              <Field label="Loaded">{d.loaded_km} km</Field>
              <Field label="Price">€{d.chosen_load!.price_eur}</Field>
              <Field label="Margin">
                <span className="font-semibold text-strategist">
                  €{d.expected_margin_eur}
                </span>
              </Field>
            </div>
            <div className="mt-2 text-xs text-slate-300">{d.explanation}</div>
          </div>
          <div className="mt-3 max-h-56 overflow-auto rounded border border-slate-700">
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 bg-slate-800 text-left text-slate-300">
                <tr>
                  <th className="px-2 py-1">#</th>
                  <th className="px-2 py-1">Cargo</th>
                  <th className="px-2 py-1 text-right">Detour</th>
                  <th className="px-2 py-1 text-right">Loaded</th>
                  <th className="px-2 py-1 text-right">Price</th>
                  <th className="px-2 py-1 text-right">Margin</th>
                  <th className="px-2 py-1 text-center">Compliant</th>
                </tr>
              </thead>
              <tbody>
                {d.score_table.slice(0, 10).map((r) => (
                  <tr
                    key={r.load_id}
                    className={
                      "border-t border-slate-800 " +
                      (r.compliant ? "" : "text-slate-500")
                    }
                  >
                    <td className="px-2 py-1 font-mono">{r.load_id}</td>
                    <td className="px-2 py-1">
                      <code>{r.cargo_type}</code>
                    </td>
                    <td className="px-2 py-1 text-right">{r.empty_detour_km}</td>
                    <td className="px-2 py-1 text-right">{r.loaded_km}</td>
                    <td className="px-2 py-1 text-right">{r.price_eur}</td>
                    <td className="px-2 py-1 text-right">
                      {r.expected_margin_eur}
                    </td>
                    <td className="px-2 py-1 text-center">
                      {r.compliant ? "✓" : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

// ---------- 4. Documents ----------

function DocumentsCard({ state }: { state: MatchState }) {
  const cmr = state.documents.cmr as Record<string, any>;
  const san = state.documents.sanitization as Record<string, any>;
  const downloadJson = (name: string, payload: unknown) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <Card accent="border-documents/60" badge="4" badgeColor="bg-documents">
      <CardTitle>Mock compliance documents</CardTitle>

      {cmr.status === "NOT_ISSUED" ? (
        <div className="mt-2 text-xs text-slate-400">{String(cmr.reason)}</div>
      ) : (
        <div className="mt-2 rounded border border-documents/40 bg-documents/5 p-2 text-xs">
          <div className="font-semibold text-documents">
            CMR · {String(cmr.consignment_number)}
          </div>
          <div className="text-slate-400">
            sender: {String((cmr.boxes as any)["01_sender"]?.name)} · cargo:{" "}
            <code>{String((cmr.boxes as any)["09_nature_of_goods"])}</code> ·
            weight: {String((cmr.boxes as any)["11_gross_weight_kg"])} kg
          </div>
          <button
            className="mt-2 rounded bg-documents/30 px-2 py-1 text-xs hover:bg-documents/50"
            onClick={() => downloadJson(`${cmr.consignment_number}.json`, cmr)}
          >
            ⬇ download CMR JSON
          </button>
        </div>
      )}

      <div className="mt-2 rounded border border-documents/40 bg-documents/5 p-2 text-xs">
        <div className="font-semibold text-documents">
          Declaratie sanitizare · {String(san.declaration_number)}
        </div>
        <div className="text-slate-400">{String(san.sanitisation_basis)}</div>
        {san.next_cargo_authorisation && (
          <div className="text-slate-300">
            next cargo: <code>
              {String((san.next_cargo_authorisation as any).cargo_type)}
            </code>{" "}
            · approved:{" "}
            {(san.next_cargo_authorisation as any).approved ? "✓" : "—"}
          </div>
        )}
        <button
          className="mt-2 rounded bg-documents/30 px-2 py-1 text-xs hover:bg-documents/50"
          onClick={() => downloadJson(`${san.declaration_number}.json`, san)}
        >
          ⬇ download sanitisation JSON
        </button>
      </div>
    </Card>
  );
}

// ---------- shared bits ----------

function Card({
  accent,
  badge,
  badgeColor,
  children,
}: {
  accent: string;
  badge: string;
  badgeColor: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`relative rounded-lg border bg-slate-800/60 p-4 shadow-sm ${accent}`}
    >
      <div
        className={`absolute -left-3 -top-3 flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold text-slate-900 ${badgeColor}`}
      >
        {badge}
      </div>
      {children}
    </div>
  );
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-base font-semibold text-slate-100">{children}</div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm text-slate-100">{children}</div>
    </div>
  );
}

function Pill({
  className,
  children,
}: {
  className: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs font-medium ${className}`}
    >
      {children}
    </span>
  );
}

function statusPillClass(status: string): string {
  switch (status) {
    case "empty":
      return "bg-emerald-700/40 text-emerald-200";
    case "loaded":
      return "bg-amber-700/40 text-amber-200";
    case "returning":
      return "bg-sky-700/40 text-sky-200";
    default:
      return "bg-slate-700/60 text-slate-300";
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-GB", {
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

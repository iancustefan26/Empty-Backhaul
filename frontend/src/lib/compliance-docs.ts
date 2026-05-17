/**
 * Per-(load, van) compliance document derivation.
 *
 * For the demo: when the dispatcher clicks a van's route on the map, we
 * surface the paperwork required for that specific cargo + carrier pair.
 * The rules below mirror what `analyst_fleet()` checks on the backend
 * — but rendered as legal documents instead of pass/fail predicates, so
 * the dispatcher knows exactly what to print, sign, or attach before
 * the truck rolls.
 *
 * Sources of truth (kept short for the tooltip rendering):
 *  - CMR        →  Geneva Convention 1956, transposed by HG 38/2008 (RO)
 *  - GDP log    →  Directive 2013/C 343/01, ANMDM Order 761/2015
 *  - ANSVSA     →  Order 111/2008 (vehicle wash & disinfection)
 *  - Cold chain →  Reg. (EC) 853/2004, Reg. (EU) 37/2005
 *  - ADR        →  ADR 2025 + Romanian OUG 109/2005
 *
 * Status semantics:
 *  - "ready"    → automatic / already on file with carrier
 *  - "warning"  → conditional (e.g. cert expires in <7 days)
 *  - "missing"  → blocking; dispatcher must fix before assigning the load
 */
import type { LoadSnapshot, TruckSnapshot } from "./dispatch-types";

export type DocStatus = "ready" | "warning" | "missing";

export interface RouteDocument {
  document: string;
  why: string;
  status: DocStatus;
  detail?: string;
}

/**
 * Returns the ordered checklist of documents this (van, load) pair needs.
 * "Ordered" = always-required first, then cargo-specific, then carrier-
 * conditional. Order is what the dispatcher will read top-to-bottom.
 */
export function requiredDocs(load: LoadSnapshot, van: TruckSnapshot): RouteDocument[] {
  const docs: RouteDocument[] = [];

  // 1. Always: CMR consignment note (international + domestic freight).
  docs.push({
    document: "CMR consignment note",
    why: "Required on every freight movement (CMR Convention 1956 / HG 38/2008).",
    status: "ready",
    detail: "Auto-generated from the load record on dispatch.",
  });

  // 2. Pharma — GDP temperature log + batch sheet.
  if (load.cargo_type === "pharma") {
    docs.push({
      document: "GDP temperature log (continuous)",
      why: "EU GDP guideline 2013/C 343/01: pharma shipments need a calibrated, tamper-evident temperature recording for the full transit.",
      status: van.has_pharma_logger ? "ready" : "missing",
      detail: van.has_pharma_logger
        ? "Van fitted with calibrated logger — last calibration on file."
        : "This van has NO calibrated logger. Re-assign or fit a logger before dispatch.",
    });
    docs.push({
      document: "Batch / lot dispatch sheet",
      why: "ANMDM Order 761/2015: shipper must hand a batch list + lot numbers to the driver at pickup.",
      status: "warning",
      detail: "Collected from shipper at pickup — confirm by phone before driver leaves depot.",
    });
  }

  // 3. Sanitary wash — when current load is food-grade and last cargo
  //    was raw protein. The seed populates `wash_certificates` on each
  //    truck, but we don't surface it through the snapshot yet — so we
  //    flag it as a warning the dispatcher must verify on paper.
  const needsWash =
    (load.cargo_type === "dairy" ||
      load.cargo_type === "produce" ||
      load.cargo_type === "pharma") &&
    van.last_cargo === "raw_meat";
  if (needsWash) {
    docs.push({
      document: "ANSVSA wash & disinfection certificate",
      why: "ANSVSA Order 111/2008: any food-grade load following raw protein needs a stamped wash certificate (≤ 7 days old).",
      status: "warning",
      detail: "Verify the certificate on file is dated within the last 7 days before dispatch.",
    });
  }

  // 4. Frozen — cold-chain temperature recording (less strict than GDP
  //    but still required by EU 853/2004 for food of animal origin).
  if (load.cargo_type === "frozen") {
    docs.push({
      document: "Cold-chain temperature recording",
      why: "Reg. (EC) 853/2004 + Reg. (EU) 37/2005: continuous temperature trace for frozen food of animal origin.",
      status: "ready",
      detail: "Reefer body's built-in datalogger satisfies this — driver hands the printout at delivery.",
    });
  }

  // 5. Raw meat — sanitary transport authorisation.
  if (load.cargo_type === "raw_meat") {
    docs.push({
      document: "Sanitary transport authorisation (ANSVSA)",
      why: "ANSVSA Order 57/2010: vehicle must hold a current authorisation for raw protein.",
      status: "ready",
      detail: "On file with the carrier — included in the truck's onboard binder.",
    });
  }

  // 6. Pharma logger calibration certificate (separate document, even
  //    if the logger is fitted).
  if (load.cargo_type === "pharma" && van.has_pharma_logger) {
    docs.push({
      document: "Logger calibration certificate",
      why: "EU GDP §9.4: the calibration certificate of the on-board logger must travel with the shipment.",
      status: "ready",
      detail: "Stored in the truck's compliance folder.",
    });
  }

  return docs;
}

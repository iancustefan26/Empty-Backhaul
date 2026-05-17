/**
 * Natural-language → intent classifier for the dispatcher chat.
 * Keyword-based, supports English + Romanian phrasings the carrier
 * actually uses ("plan today", "fără broker", "caut marfă pentru
 * săptămâna viitoare", "why is van X idle", etc.).
 *
 * Ported from the Lovable bundle; see `docs/lovable-prompt.md` for the
 * mapping table.
 */
import type { CargoType, PlanOptions } from "./dispatch-types";

export type Intent =
  | { kind: "plan"; options: PlanOptions; horizon_days?: number; humanLabel: string }
  | { kind: "alternative"; rank: number }
  | { kind: "idle_explain"; van: string }
  | { kind: "compliance" }
  | { kind: "stats" }
  | { kind: "clarify"; question: string; suggestions: string[] }
  | { kind: "smalltalk"; reply: string };

const lower = (s: string) => s.toLowerCase();

function detectFleetSize(text: string): number | undefined {
  const m = lower(text).match(/(?:only |with |doar |cu )(\d+)\s*(?:vans?|dube|camioane)/);
  if (m) return parseInt(m[1], 10);
  const m2 = lower(text).match(/what if i had (\d+)/);
  if (m2) return parseInt(m2[1], 10);
  return undefined;
}

function detectSkipCargo(text: string): CargoType[] {
  const t = lower(text);
  const out: CargoType[] = [];
  if (/raw meat|carne crud[ăa]/.test(t)) out.push("raw_meat");
  if (/pharma|medicamente/.test(t) && /skip|f[ăa]r[ăa]|without/.test(t)) out.push("pharma");
  if (/dairy|l[ăa]ctate/.test(t) && /skip|f[ăa]r[ăa]|without/.test(t)) out.push("dairy");
  if (/frozen|congelat/.test(t) && /skip|f[ăa]r[ăa]|without/.test(t)) out.push("frozen");
  return out;
}

function detectVanPlate(text: string): string | undefined {
  const m = text.match(/CJ[-\s]?\d{3}(?:[-\s]?CRL)?/i);
  if (m) {
    const base = m[0].toUpperCase().replace(/\s/g, "-");
    return base.includes("CRL") ? base : `${base}-CRL`;
  }
  return undefined;
}

export function classify(input: string): Intent {
  const t = lower(input.trim());

  if (!t) return { kind: "smalltalk", reply: "Type a command to get started." };

  // "Just today" — clarify follow-up
  if (/^just today$|^plan today$/.test(t)) {
    return { kind: "plan", options: {}, humanLabel: "today's routes" };
  }

  // Why is van X idle
  if (/why .*(van|dub|camion).*(idle|stays|stă|stationar)/.test(t) || /why is .* idle/.test(t)) {
    const van = detectVanPlate(input) ?? "CJ-101-CRL";
    return { kind: "idle_explain", van };
  }

  // Compliance
  if (/complian|legi|reglement|fines?|amenz/.test(t)) {
    return { kind: "compliance" };
  }

  // Stats / costs / kilometres / fuel
  if (
    /\b(stat(istic)?s?|cost(s|uri)?|kilomet|km|fuel|gas|carburant|combustibil|empty km|deadhead|consum)\b/.test(
      t,
    )
  ) {
    return { kind: "stats" };
  }

  // Alternative plans
  const altMatch = t.match(/(?:plan|alternativ[ăa]?)\s*([1-3])/);
  if (altMatch && (t.includes("alternativ") || t.includes("show") || t.includes("arat"))) {
    return { kind: "alternative", rank: parseInt(altMatch[1], 10) };
  }
  if (/highest[- ]margin alternative|alternative plan|alt plan/.test(t)) {
    return { kind: "alternative", rank: 2 };
  }

  // Plan today
  if (/plan today|planific[ăa] (azi|ast[ăa]zi)/.test(t)) {
    return { kind: "plan", options: {}, humanLabel: "today's routes" };
  }

  // Plan tomorrow
  if (/plan tomorrow|m[âa]ine/.test(t)) {
    const opts: PlanOptions = {};
    if (/without broker|f[ăa]r[ăa] broker|skip broker/.test(t)) opts.include_broker = false;
    return { kind: "plan", options: opts, humanLabel: "tomorrow's routes" };
  }

  // Next week / next N days — clarify
  const weekMatch = t.match(/next (\d+) (day|days|week|weeks|s[ăa]pt|zile)/);
  if (
    /next week|s[ăa]pt[ăa]m[âa]na viitoare|next-week|find me cargo|caut marf[ăa]/.test(t) ||
    weekMatch
  ) {
    const num = weekMatch ? parseInt(weekMatch[1], 10) : 7;
    const days = weekMatch && /week/.test(weekMatch[2]) ? num * 7 : num;
    return {
      kind: "clarify",
      question: `I have today's loads in the system. Should I plan just today, or fan out the plan across the next ${days} working days?`,
      suggestions: ["Just today", `Plan ${days} days`, "Cancel"],
    };
  }

  // Multi-day expansion confirmation
  const planNDays = t.match(/^plan (\d+) days?$/);
  if (planNDays) {
    return {
      kind: "plan",
      options: { horizon_days: parseInt(planNDays[1], 10) },
      humanLabel: `routes across the next ${planNDays[1]} days`,
    };
  }

  // Cancel
  if (/^cancel$|^anulea[zd]/.test(t)) {
    return { kind: "smalltalk", reply: "OK, no plan generated." };
  }

  // Replan / generic plan with modifiers
  if (
    /^plan\b|^replan\b|^planific|^optimize|^optimise/.test(t) ||
    /maximize|maximi[zs]eaz/.test(t)
  ) {
    const opts: PlanOptions = {};
    if (/without broker|skip broker|no broker|f[ăa]r[ăa] broker/.test(t)) opts.include_broker = false;
    if (/no chains?|single trips? only|single only|f[ăa]r[ăa] chain/.test(t)) opts.enable_chains = false;
    const fs = detectFleetSize(input);
    if (fs) opts.fleet_size = fs;
    const skip = detectSkipCargo(input);
    if (skip.length) opts.skip_cargo = skip;
    if (/customer sla|sla over|sla peste|maximize customer/.test(t)) opts.optimize_for = "sla";

    const labels: string[] = [];
    if (opts.include_broker === false) labels.push("no broker");
    if (opts.enable_chains === false) labels.push("singles only");
    if (opts.fleet_size) labels.push(`${opts.fleet_size} vans`);
    if (opts.skip_cargo?.length) labels.push(`skip ${opts.skip_cargo.join(", ")}`);
    if (opts.optimize_for === "sla") labels.push("SLA-first");

    return {
      kind: "plan",
      options: opts,
      humanLabel: labels.length ? `replan (${labels.join(", ")})` : "replanned routes",
    };
  }

  // Hypothetical fleet size
  const fsHypo = detectFleetSize(input);
  if (fsHypo) {
    return {
      kind: "plan",
      options: { fleet_size: fsHypo },
      humanLabel: `routes with only ${fsHypo} vans`,
    };
  }

  return {
    kind: "clarify",
    question: "I'm not sure what you'd like me to do. Try one of these:",
    suggestions: [
      "Plan today's routes",
      "Find loads for next week",
      "Show what compliance saves us",
    ],
  };
}

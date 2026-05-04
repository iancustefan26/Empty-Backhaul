"""Ablation experiment for the Analyst — produces the thesis evaluation table.

Runs the same ground-truth dataset through 5 variants of the compliance
pipeline, emits per-variant accuracy / precision / recall / cost / latency,
and writes a JSON results bundle that `scripts/build_charts.py` then turns
into figures.

  Variants
  --------
  V0  Mock-only            : deterministic predicates only (no LLM)
  V1  Vanilla LLM          : pre-PR2 minimal prompt, no sanity layer
  V2  +Prompt hardening    : current hardened prompt, no sanity layer
  V3  +Sanity layer        : pre-PR2 minimal prompt + post-LLM sanity layer
  V4  Full pipeline        : current hardened prompt + post-LLM sanity layer

  Cost model
  ----------
  V1 and V3 share the same prompt → same Gemini cache key; V2 and V4 share
  the other prompt. So with the on-disk LLM cache active, the ablation makes
  at most 2 unique calls per (truck, load) pair regardless of variant count.
  For our 75-case dataset that is ~150 cold Gemini calls (~$0.30 worst case
  off-tier; $0 on the free daily quota).

Usage:

  python -m scripts.run_ablation                         # full ablation, all variants
  python -m scripts.run_ablation --out /tmp/ablation.json
  python -m scripts.run_ablation --variants V0,V4        # quick comparison
  python -m scripts.run_ablation --skip-llm              # mock-only (no Gemini key needed)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import yaml  # noqa: E402

from app.agents.analyst import (  # noqa: E402
    _SYSTEM_PROMPT as HARDENED_PROMPT,
    _build_query,
    _build_user_message,
    _evaluate_mock,
    _parse_verdict,
)
from app.agents.llm_provider import GeminiProvider, MockProvider, get_provider  # noqa: E402
from app.agents.sanity_check import apply_sanity_layer, hard_rules_verdict  # noqa: E402
from app.agents.sentry import sentry_node  # noqa: E402
from app.agents.state import (  # noqa: E402
    ComplianceVerdict,
    LoadSnapshot,
    TruckSnapshot,
    WorkflowState,
)
from app.core.config import get_settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.rag.ingest import query_corpus, query_rules  # noqa: E402
from sqlalchemy import text  # noqa: E402

GROUND_TRUTH = BACKEND_DIR / "tests" / "ground_truth.yaml"

# ---------------------------------------------------------------------------
# Vanilla prompt — captured verbatim from git revision 5445589 (pre-PR2).
# Kept as a module-level constant so V1 and V3 hash to the same cache key
# every time and re-runs are free.
# ---------------------------------------------------------------------------

VANILLA_PROMPT = """You are the Compliance Analyst inside a multi-agent
cold-chain backhaul optimisation system for Romania. Given a truck profile,
a candidate load profile, and a set of compliance rules retrieved from a
vector database, you decide whether the truck is permitted to carry that
load under Romanian (ANSVSA), EU (HACCP, GDP, EU 561/2006) and
customer-specific constraints.

You always reason step-by-step internally but you only output a single JSON
object that matches this schema EXACTLY:

{
  "is_compliant": boolean,
  "confidence":   number,     // 0.0 - 1.0
  "blockers":     string[],   // hard violations (empty list if none)
  "warnings":     string[],   // soft issues worth flagging (empty list if none)
  "reasoning":    string,     // 2-4 plain-English sentences
  "cited_rule_ids": string[]  // ids of rules from the retrieved set you relied on
}

No prose outside the JSON. No markdown fences. No keys other than the six above.
"""


# Gemini Flash pricing — used for the cost column in the results table.
# Free tier covers ~1M tokens/day; off-tier these are the published unit
# prices. Source: https://ai.google.dev/pricing  (Sept 2025, Gemini 2.5 Flash)
GEMINI_FLASH_INPUT_USD_PER_M = 0.30
GEMINI_FLASH_OUTPUT_USD_PER_M = 2.50

# Crude token estimator used when the SDK doesn't return usage metadata.
# 1 token ≈ 4 chars of English / Romanian text. Good enough for the
# headline cost figure; the thesis can call out the methodology.
def _estimate_tokens(text_in: str) -> int:
    return max(1, len(text_in) // 4)


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------

def load_cases() -> list[dict]:
    return yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))["cases"]


def resolve_truck_id(plate: str) -> int | None:
    if engine is None:
        raise RuntimeError("Database engine not configured (SUPABASE_DATABASE_URL missing).")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM trucks WHERE plate_number = :p"), {"p": plate}).first()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# One-shot per-truck context: Sentry hydration once, retrieval once per load.
# Re-used across every LLM variant so we only pay DB + RAG cost once.
# ---------------------------------------------------------------------------

def gather_truck_context(plate: str) -> dict[str, Any]:
    truck_id = resolve_truck_id(plate)
    if truck_id is None:
        raise ValueError(f"truck '{plate}' not in database")
    initial: WorkflowState = {"truck_id": truck_id, "use_mock_llm": False}
    sentry_out = sentry_node(initial)
    if sentry_out.get("error"):
        raise ValueError(f"Sentry rejected {plate}: {sentry_out['error']}")
    truck: TruckSnapshot = sentry_out["truck"]
    loads: list[LoadSnapshot] = sentry_out["available_loads"]
    by_load: dict[int, dict] = {}
    for load in loads:
        query = _build_query(truck, load)
        rules = query_rules(query, k=5)
        excerpts = query_corpus(query, k=3)
        by_load[load["id"]] = {
            "load": load,
            "rules": rules,
            "excerpts": excerpts,
        }
    return {"truck": truck, "by_load": by_load}


# ---------------------------------------------------------------------------
# Variant runners — each returns a ComplianceVerdict + per-call metadata
# ---------------------------------------------------------------------------

def _zero_meta() -> dict:
    return {"llm_calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0,
            "wall_ms": 0, "had_error": False}


def run_v0_mock(truck: TruckSnapshot, load: LoadSnapshot) -> tuple[ComplianceVerdict, dict]:
    meta = _zero_meta()
    t0 = time.perf_counter()
    v = _evaluate_mock(truck, load)
    meta["wall_ms"] = int((time.perf_counter() - t0) * 1000)
    return v, meta


def _run_llm(
    *,
    provider: GeminiProvider,
    prompt: str,
    truck: TruckSnapshot,
    load: LoadSnapshot,
    rules: list[dict],
    excerpts: list[dict],
    apply_sanity: bool,
) -> tuple[ComplianceVerdict, dict]:
    """Shared LLM-variant body. Builds the user message, calls the provider,
    parses, optionally applies the sanity layer, returns verdict + metadata.
    """
    meta = _zero_meta()
    user = _build_user_message(truck, load, rules, excerpts)
    t0 = time.perf_counter()
    try:
        raw, was_cached = provider.evaluate(prompt, user)
    except Exception as exc:
        meta["had_error"] = True
        meta["wall_ms"] = int((time.perf_counter() - t0) * 1000)
        v = ComplianceVerdict(
            load_id=load["id"], is_compliant=False, confidence=0.0,
            blockers=[f"provider failure: {type(exc).__name__}: {exc}"],
            warnings=[], reasoning="LLM call failed.",
            cited_rule_ids=[], cited_excerpts=[], sanity_overrides=[],
        )
        return v, meta
    meta["wall_ms"] = int((time.perf_counter() - t0) * 1000)
    if was_cached:
        meta["cache_hits"] = 1
    else:
        meta["llm_calls"] = 1
        meta["input_tokens"] = _estimate_tokens(prompt) + _estimate_tokens(user)
        meta["output_tokens"] = _estimate_tokens(raw)
    try:
        llm_v = _parse_verdict(raw, load["id"], excerpts)
    except Exception as exc:
        meta["had_error"] = True
        v = ComplianceVerdict(
            load_id=load["id"], is_compliant=False, confidence=0.0,
            blockers=[f"parse failure: {type(exc).__name__}"],
            warnings=[], reasoning=raw[:300],
            cited_rule_ids=[], cited_excerpts=[], sanity_overrides=[],
        )
        return v, meta

    if not apply_sanity:
        # Manually populate the sanity_overrides field so the schema stays
        # uniform across variants (caller can compare without branching).
        llm_v["sanity_overrides"] = []
        return llm_v, meta

    hard = hard_rules_verdict(truck, load)
    corrected, _ = apply_sanity_layer(llm_v, hard, truck, load)
    return corrected, meta


# ---------------------------------------------------------------------------
# Per-variant aggregator
# ---------------------------------------------------------------------------

VARIANTS = ["V0", "V1", "V2", "V3", "V4"]
VARIANT_LABELS = {
    "V0": "Mock-only (deterministic baseline)",
    "V1": "Vanilla LLM (pre-PR2 prompt, no sanity)",
    "V2": "LLM + prompt hardening",
    "V3": "LLM + sanity layer",
    "V4": "Full pipeline (prompt + sanity)",
}


def run_one_case(
    variant: str,
    truck: TruckSnapshot,
    load: LoadSnapshot,
    rules: list[dict],
    excerpts: list[dict],
    provider: GeminiProvider | None,
) -> tuple[ComplianceVerdict, dict]:
    if variant == "V0":
        return run_v0_mock(truck, load)
    if provider is None:
        raise RuntimeError(f"Variant {variant} requires an LLM provider but none was constructed.")
    if variant == "V1":
        return _run_llm(provider=provider, prompt=VANILLA_PROMPT,
                        truck=truck, load=load, rules=rules, excerpts=excerpts,
                        apply_sanity=False)
    if variant == "V2":
        return _run_llm(provider=provider, prompt=HARDENED_PROMPT,
                        truck=truck, load=load, rules=rules, excerpts=excerpts,
                        apply_sanity=False)
    if variant == "V3":
        return _run_llm(provider=provider, prompt=VANILLA_PROMPT,
                        truck=truck, load=load, rules=rules, excerpts=excerpts,
                        apply_sanity=True)
    if variant == "V4":
        return _run_llm(provider=provider, prompt=HARDENED_PROMPT,
                        truck=truck, load=load, rules=rules, excerpts=excerpts,
                        apply_sanity=True)
    raise ValueError(f"unknown variant {variant!r}")


def _classify(case: dict, verdict: ComplianceVerdict) -> str:
    exp = bool(case["expected_compliant"])
    act = bool(verdict["is_compliant"])
    if exp and act: return "TP"   # true compliant
    if (not exp) and (not act): return "TN"  # true blocked
    if exp and (not act): return "FN"  # false block (expected pass, got blocked)
    return "FP"                          # false pass (expected block, got passed)


def evaluate_variant(
    variant: str,
    cases: list[dict],
    contexts: dict[str, dict],
    provider: GeminiProvider | None,
) -> dict:
    rows: list[dict] = []
    cm = Counter()
    rule_breakdown: dict[str, Counter] = defaultdict(Counter)
    total_meta = _zero_meta()
    sanity_corrections = 0

    for case in cases:
        plate = case["truck_plate"]
        load_id = case["load_id"]
        ctx = contexts.get(plate)
        if ctx is None:
            rows.append({**case, "error": "no truck context", "actual_compliant": None})
            cm["error"] += 1
            continue
        load_ctx = ctx["by_load"].get(load_id)
        if load_ctx is None:
            rows.append({**case, "error": "load not in available_loads", "actual_compliant": None})
            cm["error"] += 1
            continue
        verdict, meta = run_one_case(
            variant, ctx["truck"], load_ctx["load"],
            load_ctx["rules"], load_ctx["excerpts"], provider,
        )
        if verdict.get("sanity_overrides"):
            sanity_corrections += 1
        for k in ("llm_calls", "cache_hits", "input_tokens", "output_tokens", "wall_ms"):
            total_meta[k] += meta[k]
        outcome = _classify(case, verdict)
        cm[outcome] += 1
        rule_breakdown[case["rule_category"]][outcome] += 1
        rows.append({
            "truck_plate": plate,
            "load_id": load_id,
            "rule_category": case["rule_category"],
            "expected_compliant": case["expected_compliant"],
            "actual_compliant": bool(verdict["is_compliant"]),
            "outcome": outcome,
            "blockers": verdict.get("blockers", [])[:2],
            "sanity_overrides": verdict.get("sanity_overrides", []),
            "wall_ms": meta["wall_ms"],
            "cache_hit": bool(meta["cache_hits"]),
        })

    correct = cm["TP"] + cm["TN"]
    total = correct + cm["FP"] + cm["FN"]
    accuracy = correct / total if total else 0.0
    precision = cm["TP"] / (cm["TP"] + cm["FP"]) if (cm["TP"] + cm["FP"]) else 0.0
    recall = cm["TP"] / (cm["TP"] + cm["FN"]) if (cm["TP"] + cm["FN"]) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    cost_usd = (
        total_meta["input_tokens"] / 1_000_000 * GEMINI_FLASH_INPUT_USD_PER_M
        + total_meta["output_tokens"] / 1_000_000 * GEMINI_FLASH_OUTPUT_USD_PER_M
    )

    per_rule = {}
    for rule, c in rule_breakdown.items():
        rcorrect = c["TP"] + c["TN"]
        rtotal = rcorrect + c["FP"] + c["FN"]
        per_rule[rule] = {
            "correct": rcorrect, "total": rtotal,
            "accuracy": rcorrect / rtotal if rtotal else 0.0,
            "TP": c["TP"], "TN": c["TN"], "FP": c["FP"], "FN": c["FN"],
        }

    return {
        "variant": variant,
        "label": VARIANT_LABELS[variant],
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion": dict(cm),
        "per_rule": per_rule,
        "llm_calls": total_meta["llm_calls"],
        "cache_hits": total_meta["cache_hits"],
        "input_tokens": total_meta["input_tokens"],
        "output_tokens": total_meta["output_tokens"],
        "estimated_cost_usd": cost_usd,
        "total_wall_ms": total_meta["wall_ms"],
        "sanity_corrections": sanity_corrections,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(BACKEND_DIR / "docs" / "ablation.json"),
                        help="Where to write the JSON results bundle.")
    parser.add_argument("--variants", default=",".join(VARIANTS),
                        help=f"Comma-separated variant ids to run (default: all). Choices: {VARIANTS}")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Run only V0 (mock); skip every variant that needs Gemini.")
    args = parser.parse_args()

    chosen = [v.strip().upper() for v in args.variants.split(",") if v.strip()]
    if args.skip_llm:
        chosen = [v for v in chosen if v == "V0"]
    bad = [v for v in chosen if v not in VARIANTS]
    if bad:
        parser.error(f"unknown variants: {bad}")

    settings = get_settings()
    needs_provider = any(v != "V0" for v in chosen)
    provider: GeminiProvider | None = None
    if needs_provider:
        if not settings.gemini_api_key:
            parser.error("GEMINI_API_KEY missing in env; can't run LLM variants. "
                         "Use --skip-llm for mock-only.")
        provider = GeminiProvider(settings.gemini_api_key)

    cases = load_cases()
    print(f"[ablation] loaded {len(cases)} ground-truth cases", file=sys.stderr)

    # Hydrate every distinct truck once so V0..V4 share the same Sentry/RAG output.
    distinct_trucks = sorted({c["truck_plate"] for c in cases})
    print(f"[ablation] hydrating {len(distinct_trucks)} trucks (Sentry + RAG)…", file=sys.stderr)
    contexts: dict[str, dict] = {}
    for plate in distinct_trucks:
        try:
            contexts[plate] = gather_truck_context(plate)
            print(f"  ok    {plate}  loads={len(contexts[plate]['by_load'])}", file=sys.stderr)
        except Exception as exc:
            print(f"  err   {plate}  {exc}", file=sys.stderr)

    started = datetime.now(timezone.utc)
    results = []
    for v in chosen:
        print(f"\n[ablation] running {v} — {VARIANT_LABELS[v]}", file=sys.stderr)
        t0 = time.perf_counter()
        r = evaluate_variant(v, cases, contexts, provider)
        elapsed = int((time.perf_counter() - t0) * 1000)
        print(f"  {v}  acc={r['accuracy']:.1%}  precision={r['precision']:.1%}  recall={r['recall']:.1%}  "
              f"F1={r['f1']:.3f}  llm_calls={r['llm_calls']}  cache_hits={r['cache_hits']}  "
              f"cost=${r['estimated_cost_usd']:.4f}  sanity_corrections={r['sanity_corrections']}  "
              f"variant_wall={elapsed}ms", file=sys.stderr)
        results.append(r)

    bundle = {
        "metadata": {
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dataset_size": len(cases),
            "trucks": distinct_trucks,
            "variants_run": chosen,
            "gemini_model": getattr(provider, "model", None),
            "pricing": {
                "input_usd_per_m_tokens": GEMINI_FLASH_INPUT_USD_PER_M,
                "output_usd_per_m_tokens": GEMINI_FLASH_OUTPUT_USD_PER_M,
            },
        },
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2, default=str))
    print(f"\n[ablation] wrote {out} ({out.stat().st_size:,} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()

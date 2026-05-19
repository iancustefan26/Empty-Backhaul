"""Pre-warm the on-disk LLM cache for the current seed.

Why this exists
---------------
Each fresh `analyst_fleet` call on a (truck, load) pair the cache hasn't
seen costs one Vertex round-trip — typically 1–10 s. On the 25-van ×
100-load demo seed that's ~750 fresh calls if you start from a cold
cache (after subtracting the ~60 % pre-blocked by hard rules), which is
many minutes of wall-clock the dispatcher console doesn't want to wait.

This script runs the analyst over the full grid AHEAD OF TIME, with a
small pool of worker threads so Vertex's per-call latency overlaps. The
RPM throttle (in `llm_provider.py`) is process-global and serialises the
total request rate regardless of thread count, so we never exceed the
configured cap. After this script finishes, every interactive plan
request hits cache and returns in sub-second.

Usage
-----
  python -m scripts.prewarm_llm_cache                  # 25 vans × 100 loads
  python -m scripts.prewarm_llm_cache --workers 4      # gentler on Vertex
  python -m scripts.prewarm_llm_cache --fleet-size 5   # warm a subset only

Re-running after a re-seed is harmless: every pair that's already cached
short-circuits in microseconds.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.analyst import (  # noqa: E402
    _SYSTEM_PROMPT, _build_query, _build_user_message, _parse_verdict,
)
from app.agents.fleet_workflow import sentry_fleet  # noqa: E402
from app.agents.llm_provider import get_provider, MockProvider  # noqa: E402
from app.agents.sanity_check import apply_sanity_layer, hard_rules_verdict  # noqa: E402
from app.rag.ingest import query_corpus, query_rules  # noqa: E402
from scripts._exp_common import cost_meter_summary  # noqa: E402


def _warm_one_pair(provider, truck, load) -> dict:
    """Evaluate a single (truck, load) pair through the full Analyst path.
    Returns a small status dict (no verdicts kept in memory — the cache
    is the artefact)."""
    hard = hard_rules_verdict(truck, load)
    if not hard["is_compliant"]:
        # Hard rules block this pair → analyst_fleet would skip the LLM
        # for it anyway. Nothing to warm.
        return {"truck_id": truck["id"], "load_id": load["id"],
                "pre_blocked": True, "cached": False, "fresh": False}

    query = _build_query(truck, load)
    rules = query_rules(query, k=5)
    excerpts = query_corpus(query, k=3)
    user_msg = _build_user_message(truck, load, rules, excerpts)
    try:
        raw, was_cached = provider.evaluate(_SYSTEM_PROMPT, user_msg)
        # Parse + sanity to mirror production path exactly (so a future
        # production call returns the identical cached response).
        try:
            llm_v = _parse_verdict(raw, load["id"], excerpts)
            apply_sanity_layer(llm_v, hard, truck, load)
        except Exception:
            pass  # parse errors don't invalidate the cache row
        return {"truck_id": truck["id"], "load_id": load["id"],
                "pre_blocked": False, "cached": was_cached,
                "fresh": not was_cached}
    except Exception as exc:
        return {"truck_id": truck["id"], "load_id": load["id"],
                "pre_blocked": False, "cached": False, "fresh": False,
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fleet-size", type=int, default=25,
                   help="How many vans to warm (default: 25 = full seed)")
    p.add_argument("--include-broker", action=argparse.BooleanOptionalAction,
                   default=True, help="Include broker loads (default: yes)")
    p.add_argument("--workers", type=int, default=8,
                   help="Number of parallel worker threads (default: 8). "
                        "Per-thread requests still pass through the global "
                        "RPM throttle; raising this helps mostly when Vertex "
                        "per-call latency is the bottleneck.")
    args = p.parse_args()

    provider = get_provider()
    if isinstance(provider, MockProvider):
        print("[prewarm] auto-resolved to MockProvider — nothing to warm. "
              "Set VERTEX_AI_API_KEY or GEMINI_API_KEY in .env first.",
              file=sys.stderr)
        return 0

    print(f"[prewarm] provider={type(provider).__name__}  "
          f"model={provider.model}  rpm_cap={provider._rpm_cap()}",
          file=sys.stderr)

    sentry = sentry_fleet(include_broker=args.include_broker,
                          fleet_size=args.fleet_size)
    if "error" in sentry:
        print(f"[prewarm] sentry error: {sentry['error']}", file=sys.stderr)
        return 1
    vans = sentry["fleet"]
    loads = sentry["available_loads"]

    pairs = [(t, l) for t in vans for l in loads]
    n_pairs = len(pairs)
    print(f"[prewarm] grid: {len(vans)} vans × {len(loads)} loads = "
          f"{n_pairs} pairs", file=sys.stderr)

    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    pre_blocked = cached = fresh = errors = 0
    last_log = t0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(_warm_one_pair, provider, t, l) for t, l in pairs]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r.get("pre_blocked"):
                pre_blocked += 1
            elif r.get("cached"):
                cached += 1
            elif r.get("error"):
                errors += 1
            else:
                fresh += 1
            # Heartbeat every ~5 s so the user sees progress
            now = time.perf_counter()
            if now - last_log > 5.0 or i == n_pairs:
                elapsed = now - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta_s = (n_pairs - i) / rate if rate > 0 else 0
                print(f"[prewarm] {i:4}/{n_pairs}  "
                      f"({100*i/n_pairs:5.1f}%)  "
                      f"blocked={pre_blocked}  cached={cached}  "
                      f"fresh={fresh}  errors={errors}  "
                      f"rate={rate:.1f} pair/s  ETA {eta_s:5.0f}s",
                      file=sys.stderr)
                last_log = now

    wall = time.perf_counter() - t0
    cost = cost_meter_summary(since=started)
    print(file=sys.stderr)
    print(f"[prewarm] DONE in {wall:.0f}s", file=sys.stderr)
    print(f"  pre-blocked (no LLM):   {pre_blocked}", file=sys.stderr)
    print(f"  cache-hit (was warm):   {cached}", file=sys.stderr)
    print(f"  newly cached (fresh):   {fresh}", file=sys.stderr)
    print(f"  errors:                 {errors}", file=sys.stderr)
    print(f"  fresh Vertex calls:     {cost['calls']}", file=sys.stderr)
    print(f"  tokens in/out:          {cost['input_tokens']:,} / {cost['output_tokens']:,}",
          file=sys.stderr)
    print(f"  spend this run:         ${cost['cost_usd']:.4f} (€{cost['cost_eur']:.4f})",
          file=sys.stderr)
    if cost["latency_ms"]:
        eff_rpm = cost["calls"] / (wall / 60) if wall > 0 else 0
        avg_ms = cost["latency_ms"] / cost["calls"] if cost["calls"] else 0
        print(f"  effective RPM:          {eff_rpm:.1f}  "
              f"(avg {avg_ms:.0f} ms/call)", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

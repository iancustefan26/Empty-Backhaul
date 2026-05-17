"""Run all four per-agent experiments and emit a single summary JSON.

  python -m scripts.run_all_experiments              # mock-mode dry run
  python -m scripts.run_all_experiments --gemini     # live-Gemini full run

Sequencing.
    A1 runs first when --gemini is set, because it's the most
    LLM-intensive stage; if it would trip the daily-quota guard, we
    abort the suite before the cheaper experiments waste any time.

    Then S2 (zero LLM cost — deterministic geometry).
    Then T1 (CP-SAT + greedy on the same compliance cache A1/A4 primed).
    Then T2 (same cache reused).

Truthfulness gate.
    Each experiment script has its own _assert_invariants block; we
    rely on Python's non-zero exit code propagating up. If any
    invariant fails, this runner stops the suite and exits non-zero —
    "don't ship half a thesis chapter on broken numbers".

Pre-flight.
    Under --gemini we hit Gemini once with a dummy "ok" prompt to
    confirm the API key works AND that our hardening (retry / RPM
    throttle / cost log) is wired correctly. If this probe fails we
    abort before any experiment runs.

Output.
    backend/docs/experiments_v2/run_summary.json    — pass/fail, cost, wall
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts._exp_common import (  # noqa: E402
    EXP_V2_DIR, cost_meter_summary, current_git_sha,
)

EXPERIMENTS = [
    # (id, description, module-name)
    ("A1", "Analyst — ablation on 146 ground-truth cases",
     "scripts.exp_a1_extended_ablation"),
    ("S2", "Sentry — driver-hours feasibility filter",
     "scripts.exp_s2_hours_filter"),
    ("T1", "Strategist — CP-SAT vs greedy nearest-margin",
     "scripts.exp_t1_cpsat_vs_greedy"),
    ("T2", "Strategist — backhaul chains vs single trips",
     "scripts.exp_t2_chains_value"),
]


def _preflight_gemini() -> tuple[bool, str]:
    """Single Gemini call to confirm the key works + hardening fires."""
    from app.agents.llm_provider import GeminiProvider, GeminiQuotaError
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.gemini_api_key:
        return False, "GEMINI_API_KEY missing in env"
    try:
        p = GeminiProvider(settings.gemini_api_key)
        text, cached = p.evaluate(
            "You return JSON only.", 'Reply with: {"ok": true}',
        )
        return True, f"pre-flight ok ({'cached' if cached else 'fresh'}; reply={text[:60]!r})"
    except GeminiQuotaError as e:
        return False, f"daily-quota guard tripped on pre-flight: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _run_one(exp_id: str, module: str, *, use_gemini: bool) -> dict:
    import subprocess
    cmd = [sys.executable, "-m", module]
    if use_gemini:
        cmd.append("--gemini")
    t0 = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    cost_before = cost_meter_summary()
    result = subprocess.run(cmd, cwd=BACKEND_DIR, capture_output=True, text=True)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    cost_after = cost_meter_summary()
    passed = result.returncode == 0
    cost_delta = {
        k: cost_after[k] - cost_before[k]
        for k in ("calls", "cache_hits", "input_tokens", "output_tokens", "cost_usd", "cost_eur")
    }
    cost_delta["cost_usd"] = round(cost_delta["cost_usd"], 4)
    cost_delta["cost_eur"] = round(cost_delta["cost_eur"], 4)
    return {
        "experiment_id": exp_id,
        "module": module,
        "passed": passed,
        "exit_code": result.returncode,
        "elapsed_ms": elapsed_ms,
        "started_at": started_at.isoformat(),
        "cost_delta": cost_delta,
        "stdout_tail": "\n".join((result.stdout or "").splitlines()[-15:]),
        "stderr_tail": "\n".join((result.stderr or "").splitlines()[-15:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gemini", action="store_true",
                        help="Run every experiment with the live Gemini API.")
    args = parser.parse_args()

    run_started = datetime.now(timezone.utc)
    print(f"[runner] start  mode={'gemini' if args.gemini else 'mock'}  "
          f"sha={current_git_sha()}", file=sys.stderr)

    if args.gemini:
        ok, msg = _preflight_gemini()
        print(f"[runner] pre-flight: {msg}", file=sys.stderr)
        if not ok:
            print("[runner] aborting before running any experiment", file=sys.stderr)
            return 2

    rows: list[dict] = []
    for exp_id, desc, mod in EXPERIMENTS:
        print(f"\n[runner] ── {exp_id} — {desc} ──", file=sys.stderr)
        row = _run_one(exp_id, mod, use_gemini=args.gemini)
        rows.append(row)
        status = "PASS" if row["passed"] else "FAIL"
        cd = row["cost_delta"]
        print(f"[runner] {exp_id}: {status}  wall={row['elapsed_ms']/1000:.1f}s  "
              f"calls={cd['calls']}  cache={cd['cache_hits']}  "
              f"cost=€{cd['cost_eur']:.4f}",
              file=sys.stderr)
        if not row["passed"]:
            print(f"[runner] STDERR TAIL:\n{row['stderr_tail']}", file=sys.stderr)
            break  # truthfulness gate: stop on first failure

    summary = {
        "run_started_at": run_started.isoformat(),
        "run_completed_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": current_git_sha(),
        "mode": "gemini" if args.gemini else "mock",
        "experiments_run": [r["experiment_id"] for r in rows],
        "all_passed": all(r["passed"] for r in rows) and len(rows) == len(EXPERIMENTS),
        "totals": cost_meter_summary(since=run_started),
        "per_experiment": rows,
    }
    EXP_V2_DIR.mkdir(parents=True, exist_ok=True)
    out = EXP_V2_DIR / "run_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[runner] wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)

    overall = "OK" if summary["all_passed"] else "FAILED"
    t = summary["totals"]
    print(f"\n[runner] === {overall} ===", file=sys.stderr)
    print(f"  total calls: {t['calls']}   cache hits: {t['cache_hits']}", file=sys.stderr)
    print(f"  tokens in:  {t['input_tokens']:,}   out: {t['output_tokens']:,}",
          file=sys.stderr)
    print(f"  cost:       ${t['cost_usd']:.4f}  (€{t['cost_eur']:.4f})",
          file=sys.stderr)

    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

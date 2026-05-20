"""Run the 4 R-series experiments on the real 123cargo Frigo dataset.

  python -m scripts.run_123cargo_experiments

Sequences R1 → R2 → R3 → R4, asserts each one's invariants, and
emits a `docs/experiments_123cargo/run_summary.json` with per-experiment
pass/fail + wall clock.

Standalone — does NOT touch the v2 suite. The v2 runner
(`run_all_experiments.py`) and its outputs stay unmodified.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts._123cargo_common import EXP_DIR, current_git_sha  # noqa: E402

EXPERIMENTS = [
    ("R1", "Small carrier baseline — 7-van Cluj fleet on real Frigo market",
     "scripts.exp_r1_small_carrier"),
    ("R2", "Depot location sensitivity — where to base the 7 vans?",
     "scripts.exp_r2_depot_location"),
    ("R3", "Fleet scaling — single-depot growth + multi-depot expansion",
     "scripts.exp_r3_fleet_scaling"),
    ("R4", "Profit response surface — full (fleet × depots) sweep",
     "scripts.exp_r4_profit_surface"),
]


def _run_one(exp_id: str, module: str) -> dict:
    cmd = [sys.executable, "-m", module]
    t0 = time.perf_counter()
    started = datetime.now(timezone.utc)
    result = subprocess.run(cmd, cwd=BACKEND_DIR, capture_output=True, text=True)
    wall_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "experiment_id":  exp_id,
        "module":         module,
        "passed":         result.returncode == 0,
        "exit_code":      result.returncode,
        "wall_ms":        wall_ms,
        "started_at":     started.isoformat(),
        "stdout_tail":    "\n".join((result.stdout or "").splitlines()[-15:]),
        "stderr_tail":    "\n".join((result.stderr or "").splitlines()[-15:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    run_started = datetime.now(timezone.utc)
    print(f"[123cargo-runner] start  sha={current_git_sha()}", file=sys.stderr)

    rows: list[dict] = []
    for exp_id, desc, mod in EXPERIMENTS:
        print(f"\n[123cargo-runner] ── {exp_id} — {desc} ──", file=sys.stderr)
        row = _run_one(exp_id, mod)
        rows.append(row)
        status = "PASS" if row["passed"] else "FAIL"
        print(f"[123cargo-runner] {exp_id}: {status}  "
              f"wall {row['wall_ms']/1000:.1f}s", file=sys.stderr)
        if not row["passed"]:
            print(f"[123cargo-runner] STDERR TAIL:\n{row['stderr_tail']}",
                  file=sys.stderr)
            break

    summary = {
        "run_started_at":   run_started.isoformat(),
        "run_completed_at": datetime.now(timezone.utc).isoformat(),
        "git_sha":          current_git_sha(),
        "experiments_run":  [r["experiment_id"] for r in rows],
        "all_passed":       (all(r["passed"] for r in rows)
                             and len(rows) == len(EXPERIMENTS)),
        "per_experiment":   rows,
    }
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    out = EXP_DIR / "run_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[123cargo-runner] wrote {out.relative_to(BACKEND_DIR.parent)}",
          file=sys.stderr)

    overall = "OK" if summary["all_passed"] else "FAILED"
    print(f"\n[123cargo-runner] === {overall} ===", file=sys.stderr)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

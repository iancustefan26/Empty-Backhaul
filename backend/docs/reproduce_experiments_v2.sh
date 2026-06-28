#!/usr/bin/env bash
#
# Reproduce the experiments_v2 chapter end-to-end.
#
#   bash docs/reproduce_experiments_v2.sh             # mock-mode dry run
#   bash docs/reproduce_experiments_v2.sh --gemini    # live Gemini full ablation
#
# Sequence:
#   1. Validate the seed dry-run.
#   2. (Optional) reseed the DB so the experiments hit the v2 dataset.
#   3. Run pytest unit-test gates (sanity_check, fleet_strategist, route_planner,
#      llm_provider_retry).
#   4. Run all four experiments through the runner; writes
#      backend/docs/experiments_v2/*.json and run_summary.json.
#
# Time:
#   mock        ~25 s    (no LLM cost)
#   --gemini    ~30-90 min depending on how warm the disk LLM cache is

set -euo pipefail

cd "$(dirname "$0")/.."   # → backend/

PY="$(cd .. && pwd)/backend/.venv/bin/python3"
[[ -x "$PY" ]] || PY="$(command -v python3)"

USE_GEMINI=""
if [[ "${1:-}" == "--gemini" ]]; then
  USE_GEMINI="--gemini"
  : "${GEMINI_API_KEY:?GEMINI_API_KEY must be set in env for --gemini}"
fi

echo "[v2] 1. seed dry-run"
"$PY" -m scripts.seed_data --dry-run

if [[ "${2:-}" == "--reseed" || "${1:-}" == "--reseed" ]]; then
  echo "[v2] 2. RESEED DB"
  "$PY" -m scripts.seed_data --reset
fi

echo "[v2] 3. pytest sanity tests"
"$PY" -m pytest tests/test_llm_provider_retry.py tests/test_sanity_check.py \
                tests/test_fleet_strategist.py tests/test_route_planner.py -q

echo "[v2] 4. prefetch Li & Lim PDPTW benchmark instances (5 instances, ~30 KB)"
for inst in lc101 lr101 lrc101 lc201 lr201; do
  "$PY" -m scripts.lilim_loader "$inst" --size 100
done

echo "[v2] 5. run all five experiments  ${USE_GEMINI:-(mock mode)}"
"$PY" -m scripts.run_all_experiments $USE_GEMINI

echo "[v2] 6. render charts (PNGs)"
"$PY" -m scripts.build_v2_charts

echo
echo "[v2] Done. Outputs under docs/experiments_v2/ + docs/figures/experiments_v2/:"
ls -la docs/experiments_v2/ | grep -v "^total" | tail -n +2
echo
ls -la docs/figures/experiments_v2/ 2>/dev/null | grep -v "^total" | tail -n +2

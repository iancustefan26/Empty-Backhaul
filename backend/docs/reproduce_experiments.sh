#!/usr/bin/env bash
#
# One-shot reproduction of the four PR4 experiments documented in
# `backend/docs/experiments.md`. Idempotent — safe to re-run.
#
#   bash docs/reproduce_experiments.sh
#
# Total runtime ≈ 1 minute. Cost: $0 (every experiment uses mock-LLM mode
# for full reproducibility — the LLM contribution to compliance is
# measured separately in `docs/evaluation.md`).
#
# Required env (from backend/.env):
#   - SUPABASE_DATABASE_URL  (Postgres + PostGIS)

set -euo pipefail

cd "$(dirname "$0")/.."        # cd into backend/

echo "==> step 1/7  reseed depot fleet (10 vans @ Cluj-Napoca + 35 loads)"
python -m scripts.seed_data --reset

echo "==> step 2/7  ingest curated 17-rule index"
python -m scripts.ingest_rules --reset

echo "==> step 3/7  Experiment A — margin + utilisation lift"
python -m scripts.exp_a_margin_lift

echo "==> step 4/7  Experiment B — compliance violation avoidance"
python -m scripts.exp_b_compliance_value

echo "==> step 5/7  Experiment C — customer + broker freight lift (HEADLINE)"
python -m scripts.exp_c_broker_lift

echo "==> step 6/7  Experiment D — fleet-size scaling"
python -m scripts.exp_d_fleet_scaling

echo "==> step 7/7  build figures + CSV"
python -m scripts.build_experiment_charts

echo
echo "Reproduction complete. Open:"
echo "  docs/experiments.md                    — thesis-ready writeup"
echo "  docs/experiments_summary.csv           — flat per-experiment table"
echo "  docs/figures/experiments/*.png         — 4 charts"
echo "  docs/experiments/{exp_a,b,c,d}.json    — raw per-experiment bundles"

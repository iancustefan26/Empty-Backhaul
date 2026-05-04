#!/usr/bin/env bash
#
# One-shot reproduction of the ablation experiment in docs/evaluation.md.
#
#   bash docs/reproduce.sh
#
# Re-seeds the database, ingests both Chroma collections, runs all 5
# ablation variants, regenerates the figures and CSV. Idempotent — safe to
# run repeatedly. The on-disk LLM cache makes repeats free after the first run.
#
# Required env (from backend/.env):
#   - SUPABASE_DATABASE_URL  (Postgres + PostGIS)
#   - GEMINI_API_KEY         (free tier is enough)

set -euo pipefail

cd "$(dirname "$0")/.."        # cd into backend/

echo "==> step 1/5  reseed fixtures"
python -m scripts.seed_data --reset

echo "==> step 2/5  ingest curated 17-rule index"
python -m scripts.ingest_rules --reset

echo "==> step 3/5  ingest primary-source corpus (multilingual model downloads ~250 MB on first run)"
python -m scripts.ingest_corpus --reset

echo "==> step 4/5  run ablation (5 variants × 75 cases)"
python -m scripts.run_ablation --out docs/ablation.json

echo "==> step 5/5  build charts + CSV"
python -m scripts.build_charts --in docs/ablation.json --out docs/figures

echo
echo "Reproduction complete. Open:"
echo "  docs/evaluation.md            -- thesis-ready writeup"
echo "  docs/results.csv              -- flat per-variant table"
echo "  docs/figures/*.png            -- 6 charts"
echo "  docs/ablation.json            -- raw results bundle"

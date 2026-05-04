# Agentic Cold Backhaul Optimizer for Romania

Bachelor Thesis prototype: a multi-agent system that matches empty returning
refrigerated trucks (reefers) with temperature-sensitive backhaul loads while
enforcing Romanian and EU compliance (ANSVSA, HACCP, GDP).

## Architecture

- **Backend** (`/backend`) — Python, FastAPI, SQLAlchemy, Supabase (Postgres + PostGIS),
  LangGraph/CrewAI agents over Anthropic Claude, Chroma vector DB, Google OR-Tools.
- **Frontend** (`/frontend`) — React + Vite + TypeScript + Tailwind, react-leaflet map.

## Build phases

1. **Phase 1** — Project scaffolding, Supabase connection, SQLAlchemy models, Alembic migration.
2. **Phase 2** — Synthetic Romanian data seeding (10 trucks, 20 loads, wash certificates).
3. **Phase 3** — RAG (Chroma) + multi-agent workflow (Sentry / Analyst / Strategist). ← *current*
4. **Phase 4** — FastAPI endpoints (`/api/match`, `/api/trucks/live`) + mock CMR/Sanitizare docs.
5. **Phase 5** — React dashboard with Romania map + agentic reasoning feed.

## Quick start

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: paste your Supabase Postgres connection string and (optionally) a Gemini key

# 1. create PostGIS + tables in Supabase
alembic upgrade head

# 2. seed synthetic Romanian fixtures (idempotent)
python -m scripts.seed_data --reset       # wipe + reseed
python -m scripts.seed_data --dry-run     # validate fixtures without DB

# 3. ingest the compliance rule corpus into Chroma (~80 MB ONNX model on first run)
python -m scripts.ingest_rules --reset

# 3b. ingest the primary-source legal corpus (EU PDFs + ANSVSA Romanian texts)
#     ~250 MB multilingual sentence-transformer model downloads on first run.
python -m scripts.ingest_corpus --reset

# 4. run the agentic match for a specific truck
python -m scripts.run_match_demo --plate B-202-CBO --mock-llm     # deterministic Analyst, no API key needed
python -m scripts.run_match_demo --plate B-202-CBO                # uses LLM_PROVIDER (auto: prefers Gemini)

# 5. run the API
uvicorn app.main:app --reload
```

### Analyst LLM provider & cost

The Analyst can run against three backends, selected via `LLM_PROVIDER`
(`auto` | `gemini` | `anthropic` | `mock`):

| Provider | Env var | Cost | Notes |
|---|---|---|---|
| Gemini (default in `auto`) | `GEMINI_API_KEY` | Free tier covers ~1M tokens/day | Fast, cheap, recommended for development. Get a key at https://aistudio.google.com/apikey. |
| Anthropic Claude | `ANTHROPIC_API_KEY` | Paid (Haiku ≈ $0.80/M input) | Same API contract; good for cross-checking. |
| Mock (deterministic) | — | Free | No LLM at all. Exercised by `--mock-llm` and tests; lets you demo the full pipeline offline. |

Token-budget guards baked in: each LLM call is capped at 512 output tokens,
and responses are cached on disk under `backend/.llm_cache/` (keyed by a
SHA256 of the full prompt). Re-running the same `(truck, load)` demo is
free after the first run. Disable with `LLM_CACHE=0`.

`GET http://localhost:8000/health` should return `{"status": "ok"}`.

### What the seed creates

- **10 trucks** finishing deliveries in Cluj-Napoca, Timișoara, Iași, Constanța and Sibiu
  and returning to Bucharest or Oradea — mix of `chilled`, `frozen`, `multi_temp`,
  `pharma_2_8`, and `ambient` capability. Two carry calibrated pharma loggers.
- **20 backhaul loads** spanning pharma 2-8 °C, raw poultry, raw meat, dairy,
  frozen vegetables, frozen fish, produce, ambient dry goods and industrial chemicals,
  with realistic Romanian shippers (Antibiotice Iași, Albalact, Bonduelle, etc.).
- **2 wash certificates** — one ANSVSA-official sanitisation that *unblocks* a
  raw-meat truck for dairy, one deep wash on a chemicals truck that *does not*
  unblock food-grade reuse. These set up the HACCP / GDP test cases for Phase 3.

### Phase 3 — Agentic match engine

The Phase 3 pipeline lives in `backend/app/agents/` and is orchestrated by
LangGraph:

1. **Sentry** ([`app/agents/sentry.py`](backend/app/agents/sentry.py)) — hydrates a
   truck snapshot from Supabase including its current PostGIS coordinates and
   any wash certificates currently in validity, plus all `status='available'`
   loads with a future pickup window.
2. **Analyst** ([`app/agents/analyst.py`](backend/app/agents/analyst.py)) — for each
   load, queries the Chroma collection for the top-5 most similar compliance
   rules, then asks Claude (default `claude-haiku-4-5`, override via
   `ANTHROPIC_MODEL`) to render a JSON verdict with cited rule ids. Falls back
   automatically to a deterministic mock evaluator when no `ANTHROPIC_API_KEY`
   is configured or `--mock-llm` is passed.
3. **Strategist** ([`app/agents/strategist.py`](backend/app/agents/strategist.py)) —
   filters the compliant subset, scores each load by
   `price − 0.85 €/km × (deadhead + loaded km)`, and runs an OR-Tools CP-SAT
   model (`Σx ≤ 1`, maximise total margin in cents) to choose at most one load.

The 14-rule compliance corpus
([`app/rag/compliance_rules.py`](backend/app/rag/compliance_rules.py)) covers HACCP
cross-contamination, Romanian ANSVSA wash certificates, EU GDP pharma rules,
EU 561/2006 driver hours, temperature-band capability matching, the
load-declared forbidden-prior-cargo list, fish-odour cross-contamination, and
CMR documentation requirements.

#### Two-tier RAG: curated rules + primary-source corpus

The Analyst queries **two** Chroma collections per `(truck, load)` pair:

1. **`compliance_rules`** — the 17 hand-written, English rule summaries above.
   Embedded with `all-MiniLM-L6-v2` (English-only). The LLM cites these by
   stable `rule_id` (e.g. `haccp.raw-meat-to-non-meat-requires-ansvsa-wash`).

2. **`compliance_corpus`** — verbatim chunks (~900 chars each, 682 total) of
   the primary sources in [`backend/legal_documents/`](backend/legal_documents/):
   EU regulations 178/2002 and 852/2004, the EU HACCP guidance notice, and
   the four Romanian ANSVSA orders. Embedded with the multilingual model
   `paraphrase-multilingual-MiniLM-L12-v2` so English queries can retrieve
   the Romanian ANSVSA passages. The LLM quotes 1-2 sentences from any
   relevant excerpt into the verdict's `cited_excerpts` field, which the
   reasoning feed renders inline under each verdict row.

This hybrid keeps citations stable (the curated `rule_id` index never moves)
while grounding every verdict in the actual legal text — useful for thesis
defence and for the demo. Run `python -m scripts.ingest_corpus --reset` to
(re-)build the corpus collection.

#### Deterministic post-LLM sanity layer

The Analyst's hard rules (temperature capability, pharma logger, chemicals
quarantine, forbidden_prior_cargo with ANSVSA wash override) live in
[`app/agents/sanity_check.py`](backend/app/agents/sanity_check.py) as pure
predicates. After every LLM verdict, the same predicates re-run; if they
disagree on `is_compliant` or `blockers`, the deterministic answer wins and
the corrected verdict carries a `sanity_overrides` list naming which rule
was enforced (e.g. `wash-override-missed`,
`chemicals-quarantine-missed`). The LLM still owns reasoning prose, warnings,
and citation picks.

The reasoning feed shows an amber `auto-corrected` pill on any verdict the
sanity layer touched. The Analyst card header reports the total
`sanity_overrides_count` for the run.

#### Evaluation: 5-variant ablation study

The thesis evaluation lives at
[`backend/docs/evaluation.md`](backend/docs/evaluation.md). Headline result on a
75-case ground-truth dataset:

| Variant | Accuracy | Notes |
|---|---:|---|
| V1 vanilla LLM (pre-PR2 prompt, no sanity) | **89.3%** | 8 misses, all in `forbidden_prior_cargo` and `wash_override` rules |
| V2 LLM + prompt hardening | **100.0%** | worked examples eliminate every miss |
| V3 LLM + sanity layer | **100.0%** | sanity layer fires on exactly the 8 V1 misses |
| V4 full pipeline (V2 + V3) | **100.0%** | sanity layer silent (defence in depth) |

Re-run the full experiment in ~4 minutes (free on Gemini's daily quota):

```bash
cd backend && bash docs/reproduce.sh
```

Outputs land in `backend/docs/`: `evaluation.md` (writeup), `results.csv`
(per-variant numbers), `figures/*.png` (six thesis-ready charts),
`ablation.json` (raw bundle).

#### Eval harness + tests

A small ground-truth dataset
([`tests/ground_truth.yaml`](backend/tests/ground_truth.yaml)) pins 31
hand-labelled (truck, load) → expected_compliance pairs covering the README's
worked-demo scenarios + the QA edge cases. Two ways to run it:

```bash
python -m scripts.run_eval                          # mock provider, ~3 minutes, free
python -m scripts.run_eval --provider gemini        # live, ~$0 on free tier
python -m scripts.run_eval --json > eval.json       # machine-readable
```

Current accuracy: **100% on both mock and live Gemini** (Gemini's mistakes
get caught by the sanity layer).

Pytest gates the predicates with 23 unit tests plus a smoke gate that
asserts the eval stays at ≥95%:

```bash
cd backend && pytest tests/ -v
```

Worked demo (mock Analyst, no API key):

| Truck | Scenario | Compliant / 20 | Strategist pick |
|---|---|---|---|
| `B-202-CBO` | pharma capable + logger, in Cluj-Napoca | 11 | Load 1 (pharma Cluj→Buc, 0 km deadhead, €1514 margin) |
| `B-909-CBO` | last_cargo=raw_meat, no wash cert | 7 | Load 4 (raw_meat Cluj→Brașov, €457 margin) — all 5 dairy/produce loads correctly rejected |
| `OR-404-CBO` | last_cargo=raw_meat, **valid ANSVSA wash cert** | 17 | Load 3 (raw_poultry Timișoara→Oradea, 0 km, €460) — wash cert unblocks all 5 dairy/produce loads |
| `OR-303-CBO` | frozen-only, in Timișoara | 6 | Load 7 (frozen_veg Timișoara→Oradea, 0 km, €380) |
# Empty-Backhaul

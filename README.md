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
# edit .env: paste your Supabase Postgres connection string

# 1. create PostGIS + tables in Supabase
alembic upgrade head

# 2. seed synthetic Romanian fixtures (idempotent)
python -m scripts.seed_data --reset       # wipe + reseed
python -m scripts.seed_data --dry-run     # validate fixtures without DB

# 3. ingest the compliance rule corpus into Chroma (~80 MB ONNX model on first run)
python -m scripts.ingest_rules --reset

# 4. run the agentic match for a specific truck
python -m scripts.run_match_demo --plate B-202-CBO --mock-llm     # deterministic Analyst, no API key needed
python -m scripts.run_match_demo --plate B-202-CBO                # uses Anthropic Claude (requires ANTHROPIC_API_KEY)

# 5. run the API
uvicorn app.main:app --reload
```

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

Worked demo (mock Analyst, no API key):

| Truck | Scenario | Compliant / 20 | Strategist pick |
|---|---|---|---|
| `B-202-CBO` | pharma capable + logger, in Cluj-Napoca | 11 | Load 1 (pharma Cluj→Buc, 0 km deadhead, €1514 margin) |
| `B-909-CBO` | last_cargo=raw_meat, no wash cert | 7 | Load 4 (raw_meat Cluj→Brașov, €457 margin) — all 5 dairy/produce loads correctly rejected |
| `OR-404-CBO` | last_cargo=raw_meat, **valid ANSVSA wash cert** | 17 | Load 3 (raw_poultry Timișoara→Oradea, 0 km, €460) — wash cert unblocks all 5 dairy/produce loads |
| `OR-303-CBO` | frozen-only, in Timișoara | 6 | Load 7 (frozen_veg Timișoara→Oradea, 0 km, €380) |
# Empty-Backhaul

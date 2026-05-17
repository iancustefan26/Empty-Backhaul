#!/usr/bin/env bash
#
# 30-second client demo — one command makes the app demo-ready.
#
#   bash docs/demo.sh
#
# What this does:
#   1. Refreshes the seed (15 vans + 60 freight loads with TODAY-relative dates).
#   2. Warms the LLM cache so the first plan request is sub-second even if
#      `Use mock data` is unchecked in the UI.
#   3. Starts the FastAPI backend on :8000 and the Vite dev server on :5173.
#   4. Prints the demo URL + the 3-beat talk-track.
#
# After the demo, run `bash docs/demo-stop.sh` (created on first run) to
# shut everything down.
#
# Required env (from backend/.env):
#   - SUPABASE_DATABASE_URL  (Postgres + PostGIS)
#   - GEMINI_API_KEY         (only needed if you want to demo the live LLM —
#                             the script warms the mock cache by default,
#                             which is what the UI uses out of the box)

set -euo pipefail

cd "$(dirname "$0")/.."          # → backend/

GREEN='\033[0;32m'; CYAN='\033[0;36m'; ORANGE='\033[0;33m'; BOLD='\033[1m'; NC='\033[0m'
say() { printf "${CYAN}▶${NC} %s\n" "$*"; }
ok()  { printf "${GREEN}✓${NC} %s\n" "$*"; }

# Pick the backend's pinned Python — fall back to whatever is on $PATH.
PY="$(cd .. && pwd)/backend/.venv/bin/python3"
[[ -x "$PY" ]] || PY="$(command -v python3)"

# ---------- 1. Refresh fixtures (today-anchored) ----------
say "Refreshing fleet + load pool (15 vans, 60 freight loads, dates anchored to today)…"
"$PY" -m scripts.seed_data --reset > /tmp/demo-seed.log 2>&1
ok "Seed: $(grep -E 'trucks|load_requests|wash_certificates' /tmp/demo-seed.log | tr -s ' \n' ' ')"

# ---------- 2. Bring up backend ----------
# Kill any stale uvicorn first (makes the script idempotent).
pkill -f "uvicorn app.main" >/dev/null 2>&1 || true
sleep 1

say "Starting FastAPI backend on :8000…"
nohup "$PY" -m uvicorn app.main:app --port 8000 --log-level warning \
  > /tmp/demo-uvicorn.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > /tmp/demo-backend.pid

# Wait until /health responds.
for i in {1..30}; do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
  sleep 0.5
done
if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "Backend failed to start. See /tmp/demo-uvicorn.log" >&2
  exit 1
fi
ok "Backend up: $(curl -s http://127.0.0.1:8000/health)"

# ---------- 3. Warm the cache ----------
# The mock-LLM path is what the UI uses by default. One pre-call ensures
# the Chroma collections are loaded in process and the optimiser is JIT-warm.
say "Warming the optimiser…"
curl -sf -X POST 'http://127.0.0.1:8000/api/route/plan?top_k=3&mock_llm=true' -o /tmp/demo-plan.json
PLAN_MARGIN=$("$PY" -c "import json; d=json.load(open('/tmp/demo-plan.json')); print(int(d['optimiser']['alternatives'][0]['total_fleet_margin_eur']))")
PLAN_VANS=$("$PY" -c "import json; d=json.load(open('/tmp/demo-plan.json')); a=d['optimiser']['alternatives'][0]; print(a['plans'].__len__() - a['idle_count'])")
PLAN_CHAINS=$("$PY" -c "import json; d=json.load(open('/tmp/demo-plan.json')); print(d['optimiser']['alternatives'][0]['chain_trips_count'])")
PLAN_MS=$("$PY" -c "import json; d=json.load(open('/tmp/demo-plan.json')); print(d['optimiser']['elapsed_ms'])")
PLAN_TOTAL_KM=$("$PY" -c "import json; d=json.load(open('/tmp/demo-plan.json')); print(int(d['optimiser']['alternatives'][0]['total_km']))")
PLAN_EMPTY_KM=$("$PY" -c "import json; d=json.load(open('/tmp/demo-plan.json')); print(int(d['optimiser']['alternatives'][0]['total_empty_km']))")
ok "Today's plan ready: ${BOLD}€${PLAN_MARGIN} margin, ${PLAN_VANS} vans on the road, ${PLAN_CHAINS} backhaul chains, ${PLAN_MS} ms${NC}"

# ---------- 4. Bring up the frontend ----------
pkill -f vite >/dev/null 2>&1 || true
sleep 1

FRONTEND_DIR="$(cd .. && pwd)/frontend"
say "Starting frontend (Vite) on :5173…"
(cd "$FRONTEND_DIR" && nohup npm run dev > /tmp/demo-vite.log 2>&1 &)
sleep 3
for i in {1..15}; do
  if curl -sf http://127.0.0.1:5173/ >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! curl -sf http://127.0.0.1:5173/ >/dev/null 2>&1; then
  echo "Frontend failed to start. See /tmp/demo-vite.log" >&2
  exit 1
fi
ok "Frontend up: http://localhost:5173"

# ---------- 5. Stop script for cleanup ----------
cat > "$(pwd)/docs/demo-stop.sh" <<'STOP'
#!/usr/bin/env bash
set -euo pipefail
pkill -f "uvicorn app.main" >/dev/null 2>&1 || true
pkill -f vite >/dev/null 2>&1 || true
echo "✓ Demo servers stopped."
STOP
chmod +x docs/demo-stop.sh

# ---------- 6. Print the talk-track ----------
cat <<EOF

${BOLD}🎯 Demo is ready. Open in incognito so localStorage is empty:${NC}

   ${BOLD}${CYAN}http://localhost:5173${NC}

${BOLD}┌─ The 3-beat talk-track ─────────────────────────────────────────────┐${NC}

  ${BOLD}Beat 1 — "Plan today's routes"${NC}
    ${ORANGE}Type:${NC}  Plan today's routes
    ${ORANGE}Say:${NC}   "Cluj-based carrier — 15 vans, 60 loads on offer.
            The dispatcher just asks in plain English. Sub-second.
            We get 3 alternative plans with different profits;
            Option 1 is the best at €${PLAN_MARGIN}."

  ${BOLD}Beat 2 — Click a route on the map${NC}
    ${ORANGE}Click:${NC} Any coloured polyline (try a CHAIN — Cluj → X → Y → Cluj)
    ${ORANGE}Say:${NC}   "One click and the dispatcher sees the cargo,
            the shipper's contact, and the exact compliance documents
            needed to be fully legal — CMR, GDP log, ANSVSA wash cert,
            cold-chain trace. Each one tagged READY / VERIFY / MISSING."

  ${BOLD}Beat 3 — "Show me costs and km"${NC}
    ${ORANGE}Type:${NC}  Show me the estimated costs, total kilometers and empty kilometers
    ${ORANGE}Say:${NC}   "Today the fleet runs ${PLAN_TOTAL_KM} km, of which ${PLAN_EMPTY_KM} are empty.
            At today's diesel price the system breaks down fuel,
            operating cost, revenue and margin — the dispatcher sees
            instantly what the day is actually worth."

${BOLD}└─────────────────────────────────────────────────────────────────────┘${NC}

  ${ORANGE}Tips${NC}
   ·  Open Chrome ${BOLD}incognito${NC}: clean chat history, no surprises.
   ·  Pre-zoom the browser to ~110 % so text is comfortable on a projector.
   ·  Leave the "Use mock data (faster)" toggle ${BOLD}on${NC} for the demo —
      every interaction stays sub-second.
   ·  If a chain route is hard to spot, expand "See N vans dispatched" in
      the chat card; rows tagged ${BOLD}CHAIN${NC} are the multi-leg trips.

${BOLD}When the demo ends:${NC}  bash docs/demo-stop.sh

EOF

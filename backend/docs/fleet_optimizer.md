# Fleet optimiser — multi-truck assignment with compliance and driver-hours feasibility

This is the thesis chapter for the fleet-level Strategist. It generalises
the single-truck pick-one introduced in earlier chapters into a fleet-wide
assignment problem solved with OR-Tools CP-SAT, with hard constraints on
HACCP/ANSVSA/GDP compliance (delegated to the Analyst from earlier
chapters) and EU Regulation 561/2006 driving-hours feasibility (enforced
inside the optimiser).

> **Headline claim.** For a Romanian SMB carrier dispatching 10–15
> refrigerated trucks against a mix of contracted-customer freight and
> spot-market broker freight, a multi-vehicle CP-SAT optimiser computes
> the top-3 alternative assignment plans in under 100 ms while
> guaranteeing zero compliance violations. The same engine ships behind
> `POST /api/match/fleet` and the dashboard's "Fleet" tab.

---

## 1. Problem statement

A small refrigerated-transport carrier in Romania operates a fleet of
**N empty trucks** at the end of each delivery cycle. Each truck has:

- a current location *(lat, lon)*,
- a temperature capability ∈ *{frozen, chilled, multi_temp, pharma_2_8, ambient}*,
- a last-cargo memory (HACCP cross-contamination relevance),
- a remaining EU-561/2006 driving-hours budget,
- optionally a calibrated pharma 2-8 °C logger,
- optionally one or more wash certificates that may or may not unlock
  food-grade reuse depending on prior cargo and certificate type.

The carrier sees **M available backhaul loads** drawn from two pools:

- **Customer pool** — direct contractual relationships. Serving these is
  the carrier's commercial bread-and-butter; dropping a customer load
  is an SLA risk.
- **Broker pool** — spot-market freight from exchanges (Trans.eu,
  Timocom, Bursa Transport in Romania). Margins are 10–20 % below
  customer rates but they exist to fill empty backhauls.

The dispatcher must choose **which truck takes which load** such that:

- no truck is double-booked,
- no load is double-served,
- every match is compliant under HACCP / ANSVSA / EU GDP,
- every truck has the driving-hours budget to do the trip, and
- **total fleet margin** (price minus per-km cost over both empty and
  loaded segments) is maximised.

The output should be the **top-K alternative plans** ranked by
margin, so the dispatcher can pick by criteria the model cannot quantify
(driver preference, customer-relationship value, weather, etc.).

---

## 2. Mathematical formulation

Let `T` be the set of empty trucks and `L` be the set of available loads.
Let `C ⊆ T × L` be the set of (truck, load) pairs that are
**compliant** (Analyst verdict says `is_compliant = true`) **and**
**hours-feasible** (estimated drive time + buffer ≤ remaining budget)
**and** **profitable** (margin > 0).

For every `(t, l) ∈ C` define the binary decision variable

$$
x_{t,l} \in \{0, 1\} \;.
$$

Define the per-pair margin in cents

$$
\text{margin}_{t, l}
  = \big(\text{price}_l - 0.85 \cdot (\text{empty\_km}_{t,l} + \text{loaded\_km}_l)\big) \cdot 100
$$

and the customer-loyalty bonus

$$
\beta_l = \begin{cases}
500 & \text{if load } l \text{ is from the customer pool} \\
0 & \text{otherwise}
\end{cases}
$$

(value chosen to break ties without ever overriding a materially-better
broker margin; verified by the unit test
[`test_customer_loyalty_does_not_override_higher_margin`](backend/tests/test_fleet_strategist.py)).

The optimisation problem is

$$
\begin{aligned}
\max_{x} \quad & \sum_{(t, l) \in C} (\text{margin}_{t, l} + \beta_l) \cdot x_{t, l} \\
\text{s.t.} \quad
& \sum_{l : (t,l) \in C} x_{t, l} \le 1 \quad \forall t \in T \\
& \sum_{t : (t,l) \in C} x_{t, l} \le 1 \quad \forall l \in L \\
& x_{t, l} \in \{0, 1\}
\end{aligned}
$$

The compliance, hours-feasibility, and profitability gates are baked
into the *construction* of `C` rather than added as extra inequalities;
this keeps the model small and the solution space clean.

---

## 3. K-best enumeration via no-good cuts

The dispatcher needs more than the optimal plan — they need the next
two or three structurally-distinct alternatives so they can pick on soft
criteria. We enumerate the top-K plans via the standard "no-good cut"
construction:

1. Solve the model. Record the chosen pair set `S₁ = { (t, l) : x_{t,l} = 1 }`.
   Yield plan 1.
2. Add the inequality
   $$
   \sum_{(t, l) \in S_1} x_{t, l} \le |S_1| - 1
   $$
   forcing the next solution to differ from `S₁` on at least one pair.
3. Re-solve. Yield plan 2 if a feasible solution exists.
4. Repeat for `K` iterations or until the model is infeasible.

This produces a **strict** ranking of K distinct plans — never two
identical assignment vectors. Pseudocode lives in
[`fleet_strategist.run_fleet_optimizer`](backend/app/agents/fleet_strategist.py).

```text
plans = []
forbidden = []
for rank in 1..K:
    model = build_base_model(C)
    for prev in forbidden:
        model.Add(sum(x[i] for i in prev) <= |prev| - 1)
    status, x_vals = solve(model)
    if status not in {OPTIMAL, FEASIBLE}: break
    chosen = { (t, l) : x_{t,l} == 1 }
    if not chosen: break
    plans.append(make_plan_with_stats(chosen, rank))
    forbidden.append(indices_of(chosen))
return plans
```

---

## 4. Per-plan statistics

For every emitted plan, `run_fleet_optimizer` returns a `FleetPlanStats`
record with the metrics a Romanian dispatcher (and a thesis evaluator)
actually cares about:

| Field | Meaning |
|---|---|
| `total_margin_eur` | Σ (price − km × 0.85 EUR/km) over all assigned pairs. |
| `total_loaded_km` | Σ road-distance from pickup to delivery for all assigned loads. |
| `total_empty_km` | Σ road-distance from each assigned truck's current position to its load's pickup. |
| `deadhead_ratio` | `empty / (empty + loaded)`. The single most-watched KPI in transport. EU industry average ≈ 28 % (Eurostat). |
| `fleet_utilization_pct` | Trucks with assignments / total trucks. Idle trucks earn nothing. |
| `customer_loads_served` / `..._available` | Direct-contract throughput. |
| `broker_loads_served` / `..._available` | How much spot-market freight got picked up to fill backhauls. |
| `unserved_customer_load_ids` | **SLA risk indicator** — customer loads that *should* have been taken but weren't because of compliance/hours/conflict. Surfaced as an amber warning in the dashboard. |
| `assignments` | Per-truck row: `(truck_plate, load_id?, pickup, delivery, empty_km, loaded_km, drive_hours, margin)`. |

---

## 5. Compliance gating — reused, not reinvented

The compliance check that decides whether a `(truck, load)` pair enters
`C` reuses the entire Analyst stack from the previous chapter:

- **Hard-rule pre-filter** — `sanity_check.hard_rules_verdict()` runs
  the deterministic predicates first. If a pair is *blocked* by a hard
  rule, we skip the LLM entirely (saves cost and latency, equally
  trustworthy because the LLM would have been overridden anyway).
- **Per-pair Analyst** — for pairs that survive the pre-filter and when
  `mock_llm=False`, the Analyst runs as in single-truck mode: queries
  the curated rule index and the multilingual primary-source corpus,
  asks Gemini for a structured verdict, applies the post-LLM sanity
  layer, attaches `cited_excerpts`.
- **EU 561/2006 hours** — enforced as a hard gate inside
  `score_pair()`: `loaded_h + empty_h + 0.5h_buffer ≤ remaining_h`. A
  pair that fails never enters `C`. The 0.5 h buffer covers mandatory
  rest stops and admin time.

Cost analysis for a 15-truck × 35-load fleet:

- Total candidate pairs: 525.
- Hard-rule pre-filter typically removes 50–70 % (incompatible
  capability or last-cargo).
- Surviving pairs go to the LLM; with the SHA-256 disk cache from the
  earlier chapter, repeats are free.
- Worst-case cold cost on Gemini Flash: ≈ $0.05 per fleet match.

---

## 6. Complexity

The base assignment problem (without the no-good cuts) is the **maximum
weight bipartite matching** problem with capacity 1 on both sides — a
classical polynomial-time problem solvable by the Hungarian algorithm in
O((|T| + |L|)³). CP-SAT solves it as a 0/1 ILP, which is NP-hard in
general but trivial for our size (|T| ≤ 15, |L| ≤ 35, |C| ≤ 525).

The K-best loop multiplies the cost by a factor of K, but each
subsequent solve becomes easier as more no-good cuts prune the search.
Empirically the solver returns the full top-3 in **under 100 ms** at
our problem size, well within real-time dispatching budget.

---

## 7. Implementation pointers

| Concern | File |
|---|---|
| Per-pair scoring (margin, hours-feasibility) | [`app/agents/fleet_strategist.py:score_pair`](backend/app/agents/fleet_strategist.py) |
| CP-SAT model + K-best loop | [`app/agents/fleet_strategist.py:run_fleet_optimizer`](backend/app/agents/fleet_strategist.py) |
| Sentry fleet hydration | [`app/agents/fleet_workflow.py:sentry_fleet`](backend/app/agents/fleet_workflow.py) |
| Per-pair compliance loop with hard-rule pre-filter | [`app/agents/fleet_workflow.py:analyst_fleet`](backend/app/agents/fleet_workflow.py) |
| End-to-end orchestrator | [`app/agents/fleet_workflow.py:run_fleet_match`](backend/app/agents/fleet_workflow.py) |
| REST endpoint | [`app/api/match.py:match_fleet`](backend/app/api/match.py) — `POST /api/match/fleet` |
| CLI demo | [`scripts/run_fleet_demo.py`](backend/scripts/run_fleet_demo.py) |
| Unit tests | [`tests/test_fleet_strategist.py`](backend/tests/test_fleet_strategist.py) |

---

## 8. Reproducing a fleet match

The demo runs locally in well under a second once Chroma and the DB are
seeded:

```bash
cd backend

# (one-time) seed the DB and ingest the compliance + corpus indices
python -m scripts.seed_data --reset
python -m scripts.ingest_rules --reset
python -m scripts.ingest_corpus --reset

# fleet match — top 3 plans, mock LLM (deterministic, free, ~50 ms total)
python -m scripts.run_fleet_demo

# customer-only mode (compare against full broker-aware mode for the experiment)
python -m scripts.run_fleet_demo --customer-only

# live Gemini for citations + reasoning (~$0.05 cold, $0 cached)
python -m scripts.run_fleet_demo --gemini

# machine-readable for the experiment harness in the next chapter
python -m scripts.run_fleet_demo --json > /tmp/fleet.json
```

API + dashboard:

```bash
uvicorn app.main:app --reload                         # backend
cd ../frontend && npm run dev                         # browser at localhost:5173
# Switch to the "Fleet" tab in the header, click "Run fleet match",
# inspect the polylines on the Romania map and the per-plan stats panel.
```

---

## 9. What's deliberately not in this chapter (covered later)

- Empty-km reduction baseline vs. our optimiser → **next chapter,
  Experiment A**.
- Compliance violation avoidance vs. naive (no-Analyst) optimiser →
  **Experiment B**.
- Customer-only vs. customer + broker mix margin lift → **Experiment C**.
- Fleet-size scaling network effect → **Experiment D**.
- Multi-leg trip planning (truck does pickup → delivery → another
  pickup the same day) — out of scope; future work.
- Multi-day planning horizon — out of scope; future work.
- Real broker-API integration (Trans.eu / Timocom) — currently
  simulated by the broker pool in the seed data.

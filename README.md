# ProductionAgent

Multi-agent production planning for window cleaning and other service-based businesses.

ProductionAgent helps an operator turn a backlog of pending jobs into a fully
sequenced production week — accounting for crew skills, equipment loadouts,
geographic proximity, time budgets, and per-client confirmations. When a
disruption hits (weather, callout, equipment failure), a dedicated agent
re-plans just the affected jobs and drafts a client-facing reschedule note.

## Design principles

The system follows Anthropic's [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) guidance:

1. **Simplicity** — no heavy agent framework. Each agent is a small class
   with an `async run(ctx)` method; the supervisor orchestrates them through
   a typed pipeline. Easy to read, easy to test, easy to debug.
2. **Transparency** — every agent emits structured `AgentEvent`s that stream
   to the UI over Server-Sent Events as the pipeline runs. The rescheduler
   in particular *enumerates* the candidate slots and scores them out loud
   before picking one.
3. **Deterministic correctness, LLM-augmented narrative** — scheduling logic
   is rule-based and fully tested. The LLM is used only to write the
   executive summary and personalize client messages, and every LLM call has
   a deterministic fallback so the product is fully demoable offline.

## Agents

| Agent | Responsibility | Anthropic pattern |
| --- | --- | --- |
| `GeoClusterAgent` | Group jobs by proximity into day-sized buckets | Workflow step |
| `CrewMatchAgent` | Assign crews & days under hard skill+equipment filters, load-balanced | Workflow step (router-like, hard-filter + soft-score) |
| `EquipmentAgent` | Validate loadouts, flag day-level contention and per-job gaps | **Parallelization (sectioning)** — runs concurrently with TimeBudget |
| `TimeBudgetAgent` | Sequence stops with travel time, compute utilization, flag overbooking | **Parallelization (sectioning)** — runs concurrently with Equipment |
| `ClientCommsAgent` | Routes each job to a tonal profile (residential / commercial / phone), drafts a message, then iterates with critic + guardrail feedback | **Routing** + **Evaluator-optimizer** + **Parallelization** (the sub-pipeline does all three) |
| `MessageCriticAgent` | Scores a drafted message 0–100 for tone, completeness, brevity; returns structured JSON when LLM is enabled | **Evaluator-optimizer (evaluator side)** |
| `MessageGuardrailAgent` | Compliance / quality check: no other-client leakage, date and arrival window stated, has a call-to-action | **Parallelization (sectioning)** — runs concurrently with the critic |
| `PlanReviewerAgent` | Scores the assembled plan (revenue, drive ratio, overbooking, equipment gaps, message quality) into KPIs + a 0–100 risk score, then writes a short narrative review | **Evaluator-optimizer (evaluator side)** |
| `ReschedulerAgent` | On disruption, enumerates *all* viable (day, crew) slots with explicit trade-off scores, then picks #1 with reasoning, resequences the day, and drafts a client note | Workflow step (transparent decision-making) |
| `SupervisorAgent` | Orchestrates the pipeline; phase 1 sequential (geo → match), phase 2 parallel (equipment ‖ budget), phase 3 comms sub-pipeline, phase 4 plan review | **Orchestrator-workers** |

### Stopping conditions

Following Anthropic's guidance to "include stopping conditions to maintain
control", the only loop in the system (the comms agent's evaluator-optimizer)
caps at **two iterations**: draft, critique, optionally redraft, then accept
whatever the second draft scored. The rescheduler is bounded by the
candidate set, not a loop.

### Ground truth

Each agent reads from a shared, typed-where-it-matters blackboard
(`AgentContext`), so every downstream agent gets fresh facts produced by
the previous step rather than passing free-form text. The final
`PlanResult` is a Pydantic model — including a `PlanReview` with
structured KPIs, a numeric risk score, and per-job `MessageQuality`
records — so downstream consumers (future evaluator-optimizer loops, a
dashboard, another agent) can branch on values, not parse text.

## Architecture

```
┌───────────────────────── SupervisorAgent (orchestrator) ───────────────────────┐
│                                                                                │
│   Phase 1 (sequential)        Phase 2 (parallel)            Phase 3 (comms)    │
│   ┌──────────┐  ┌──────────┐  ┌─────────────┐               ┌────────────────┐ │
│   │GeoCluster│→ │CrewMatch │→ │ Equipment   │ ─┐            │ ClientComms    │ │
│   └──────────┘  └──────────┘  └─────────────┘  │            │  ├─ route      │ │
│                                ┌─────────────┐ │            │  ├─ draft      │ │
│                                │ TimeBudget  │ │            │  ├─ (Critic    │ │
│                                └─────────────┘ ┘            │  │   ‖         │ │
│                                                             │  │  Guardrail) │ │
│                  Phase 4 (evaluator)                        │  ├─ revise?    │ │
│                  ┌────────────────┐                         │  └─ accept     │ │
│                  │ PlanReviewer   │ ← KPIs + risk score     └────────────────┘ │
│                  └────────────────┘                                            │
│                                                                                │
│   On disruption: ReschedulerAgent enumerates candidates → scores → picks #1    │
└────────────────────────────────────────────────────────────────────────────────┘
```

Agents share state through an `AgentContext` blackboard and emit
`AgentEvent`s as they run. The supervisor streams those events over
Server-Sent Events so the UI can render the multi-agent run live.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: see "Configuration" below
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:3000/> — the UI is a **ChatGPT-style chat** with agent traces, a draft schedule in the thread, and a **Live schedule** tab for the plan you confirm. Click **API keys** in the header for where to put your OpenAI / Supabase credentials (in `.env` on the server).

**Spreadsheet import:** paste tab-separated booking rows (like your Excel export) into the chat. Addresses are normalized (Canadian postal format, comma fixes) with a **confidence score**; rows below 82% show an editable field and must be confirmed before jobs are created.

## Configuration

Both integrations are optional. The product is fully functional offline.

### LLM — Claude agents (recommended)

Set `ANTHROPIC_API_KEY` in `.env` (and optionally `ANTHROPIC_MODEL`).
The app uses **Anthropic Claude** for plan summaries, client confirmation
messages, message critic, and address refinement. Scheduling logic stays
deterministic.

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

Faster/cheaper: `claude-3-5-haiku-20241022`. Legacy OpenAI still works with
`LLM_PROVIDER=openai` and `OPENAI_API_KEY` (use a real model id like `gpt-4o-mini`,
not `gpt-5.5`).

### Google Geocoding (recommended)

Set `GOOGLE_MAPS_API_KEY` and enable the **Geocoding API** in Google Cloud.
`GeoClusterAgent` geocodes every job (e.g. `90 Devon` → full Quebec address with
lat/lng), scores confidence (0–100%), and flags addresses outside the West Island
service area. Scores below **82%** require user confirmation on import or show
as review events in the agent trace when planning.

### Supabase (optional)

Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to:

- hydrate clients, crews, equipment, and jobs from Postgres on startup
  (instead of the in-memory demo seed), and
- persist every plan, crew-day, scheduled stop, drafted client message
  (with quality scores and guardrail flags), plan review (KPIs +
  narrative + risk score), and agent event back to the database for
  auditing and replay.

The service-role key is **server-only** — never expose it in browser
code. RLS is enabled on every table; service-role bypasses RLS so the
backend has full access.

To create the schema in a fresh Supabase project, run
[`sql/schema.sql`](./sql/schema.sql) followed by [`sql/seed.sql`](./sql/seed.sql)
(or apply them as Supabase migrations).

### Database schema

| Table | Purpose |
| --- | --- |
| `clients` | End-customers (residential, commercial, HOA) |
| `crews` | Field crews with members, skills, daily minute capacity, base location |
| `equipment` | Inventory of capital equipment (pressure washers, lifts, ladders, rope kits, vans) |
| `crew_equipment` | Many-to-many crew → equipment loadout |
| `jobs` | Service jobs to plan, with required skills/equipment, time window, status |
| `plans` | One row per produced weekly plan |
| `crew_days` | A crew's day inside a plan, with totals and warnings |
| `scheduled_stops` | Ordered stops within a crew-day |
| `client_messages` | Drafted messages with critic score and guardrail flags |
| `plan_reviews` | Structured KPIs + 0–100 risk score + narrative |
| `agent_events` | Append-only log of every agent event for auditing/replay |

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET`  | `/api/health` | Health + LLM status |
| `GET`  | `/api/jobs` · `/api/crews` · `/api/equipment` · `/api/clients` | Read seed/state |
| `GET`  | `/api/plan` | Latest plan |
| `POST` | `/api/plan` | Run the agents and return a plan |
| `POST` | `/api/plan/stream` | SSE stream of agent events + final result |
| `POST` | `/api/reschedule` | Body: `{ "job_id": "...", "reason": "..." }` |
| `POST` | `/api/jobs/{id}/confirm` | Mark a job client-confirmed |
| `POST` | `/api/jobs/{id}/cancel` | Cancel a job (also drops from plan) |
| `POST` | `/api/seed/reset` | Reset the demo dataset |
| `POST` | `/api/qa/run` | Run QA agent team; auto-launches Cursor Cloud Agent when configured |
| `POST` | `/api/qa/handoff/{run_id}` | Manually (re)launch Cursor agent for a QA report |
| `POST` | `/api/reorganize/stream` | Chat-driven replan or single-job reschedule (SSE) |
| `PUT` | `/api/preferences/scheduling` | `geo_first` \| `crew_fill` \| `balanced` |

### Automatic Cursor handoff after QA

When `CURSOR_API_KEY` is set (Cloud Agents key from the Cursor dashboard), each `POST /api/qa/run`:

1. Writes `reports/cursor-handoff_{run_id}.md` and `reports/qa_{run_id}.json`
2. **Automatically** calls the [Cursor Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints) with that report as the agent prompt
3. Returns `cursor_handoff` in the JSON response (`agent_id`, `agent_url`, `pr_url` when ready)

Configure in `.env` (see `.env.example`):

- `CURSOR_API_KEY` — required
- `CURSOR_REPOSITORY` — optional if `git remote` origin is GitHub
- `CURSOR_REF` — branch to work on (defaults to current git branch)
- `CURSOR_AUTO_HANDOFF_ON_FAIL_ONLY=true` — only launch when QA fails

Open the **QA report** tab in the UI to see launch status and a link to the cloud agent.

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

The tests run the deterministic path and validate that:

- the seed populates the store,
- a plan schedules nearly all jobs across the right crew-days,
- every specialist agent (including the PlanReviewer) emits at least one event,
- the comms agent drafts a message for every scheduled job,
- the comms agent emits routing and iteration events (the evaluator-optimizer loop),
- every scheduled job has a quality score,
- the plan review is structured (KPIs + 0–100 risk score + narrative),
- the guardrail catches missing call-to-action and other-client leakage,
- rescheduling enumerates candidates with trade-offs and picks the best explicitly, and
- high-rise jobs are placed with a rope-capable crew (no equipment gap).

## File layout

```
app/
  main.py                 FastAPI app + SSE stream
  models.py               Pydantic domain models (incl. PlanReview, MessageQuality)
  storage.py              In-memory store
  seed.py                 West Island (Montreal) booking sheet (6 jobs)
  sql/west_island_jobs.sql  Replace Supabase jobs/clients with the sheet data
  llm.py                  Optional OpenAI-compatible client
  agents/
    base.py               AgentContext, EventEmitter, geo helpers
    geo_cluster.py        GeoClusterAgent
    crew_match.py         CrewMatchAgent
    equipment.py          EquipmentAgent
    time_budget.py        TimeBudgetAgent
    client_comms.py       ClientCommsAgent (router + drafter + loop coordinator)
    message_critic.py     MessageCriticAgent (evaluator)
    message_guardrail.py  MessageGuardrailAgent (compliance/quality)
    plan_reviewer.py      PlanReviewerAgent (whole-plan evaluator)
    reschedule.py         ReschedulerAgent
    supervisor.py         SupervisorAgent (orchestrator)
static/
  index.html              Single-page UI (Tailwind + Alpine.js)
tests/
  test_planner.py         End-to-end tests (12 tests, deterministic path)
```

## Notes & next steps

- Persisting the plan to a real DB and switching to a queue-backed agent
  runner would let multiple operators collaborate on the same week.
- The geo-clustering is a simple farthest-first + nearest-seed assignment —
  swap in `scikit-learn` k-means or an OR-tools VRP solver as data grows.
- Route legs assume a flat 35 km/h drive time; integrate Google Maps or
  Mapbox Matrix API for real ETAs.
- The agents communicate via an explicit blackboard rather than an LLM-router
  on purpose: deterministic scheduling logic is easier to test, audit, and
  reproduce. The LLM augments narrative — it never gates correctness.

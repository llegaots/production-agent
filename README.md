# ProductionAgent

Multi-agent production planning for window cleaning and other service-based businesses.

ProductionAgent helps an operator turn a backlog of pending jobs into a fully
sequenced production week — accounting for crew skills, equipment loadouts,
geographic proximity, time budgets, and per-client confirmations. When a
disruption hits (weather, callout, equipment failure), a dedicated agent
re-plans just the affected jobs and drafts a client-facing reschedule note.

## Agents

Six specialist agents collaborate under a supervisor:

| Agent | Responsibility |
| --- | --- |
| `GeoClusterAgent` | Groups jobs by proximity so geographically-close work runs together |
| `CrewMatchAgent` | Assigns crews & days to clusters based on skill fit, difficulty, capacity |
| `EquipmentAgent` | Validates equipment loadouts, surfaces day-level contention and per-job gaps |
| `TimeBudgetAgent` | Sequences stops with travel-time, computes utilization, flags overbooked days |
| `ClientCommsAgent` | Drafts a per-job confirmation message for every scheduled job |
| `ReschedulerAgent` | Triggered on disruption — picks the next-best slot and drafts a reschedule note |
| `SupervisorAgent` | Orchestrates the pipeline, aggregates conflicts, writes the weekly summary |

The core scheduling logic is **deterministic and rule-based** — no LLM is
required to produce a valid plan. If an `OPENAI_API_KEY` is configured,
agents additionally use the LLM to write the weekly executive summary and
warm, personalized client messages. Otherwise, clean templates are used.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      SupervisorAgent                            │
│   ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  ┌─────┐ │
│   │ GeoCluster │→│ CrewMatch │→│ Equipment │→│ TimeBudget │→│Comms│ │
│   └─────────┘  └──────────┘  └─────────┘  └──────────┘  └─────┘ │
│                              ↓ blackboard ↓                     │
│                          Final WeekPlan                         │
└─────────────────────────────────────────────────────────────────┘
                  │
                  │ on disruption
                  ▼
            ReschedulerAgent  →  patched WeekPlan + client message
```

Agents share state through an `AgentContext` blackboard and emit
`AgentEvent`s as they run. The supervisor streams those events over
Server-Sent Events so the UI can render the multi-agent run live.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: paste an OPENAI_API_KEY for LLM-authored messages
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/> and click **Run agents** to plan the week.

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

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

The tests run the deterministic path and validate that:

- the seed populates the store,
- a plan schedules nearly all jobs across the right crew-days,
- every specialist agent emits at least one event,
- the comms agent drafts a message for every scheduled job,
- rescheduling moves a job to a different `(day, crew)` pair, and
- high-rise jobs are placed with a rope-capable crew (no equipment gap).

## File layout

```
app/
  main.py             FastAPI app + SSE stream
  models.py           Pydantic domain models
  storage.py          In-memory store
  seed.py             Sample data (ClearView Exterior Services in Austin)
  llm.py              Optional OpenAI-compatible client
  agents/
    base.py           AgentContext, EventEmitter, geo helpers
    geo_cluster.py    GeoClusterAgent
    crew_match.py     CrewMatchAgent
    equipment.py      EquipmentAgent
    time_budget.py    TimeBudgetAgent
    client_comms.py   ClientCommsAgent
    reschedule.py     ReschedulerAgent
    supervisor.py     SupervisorAgent (orchestrator)
static/
  index.html          Single-page UI (Tailwind + Alpine.js)
tests/
  test_planner.py     End-to-end tests for the rule-based path
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

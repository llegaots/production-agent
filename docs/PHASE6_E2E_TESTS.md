# Phase 6 — Orchestrator E2E tests

End-to-end tests exercise `run_scheduling_mission` against **isolated Supabase rows** seeded from YAML fixtures in `tests/scenarios/`. Each run uses a unique id prefix (`e2e-{uuid}-{scenario}-`) so dev data is never touched.

## Scenarios

| Fixture | Intent |
|---------|--------|
| `simple_week.yaml` | 30 clustered jobs, 4 crews → approve iteration 1 |
| `tight_constraints.yaml` | Narrow time windows → approve within 2 iterations |
| `preference_heavy.yaml` | Morning + preferred crews → LLM agent iterations (`@pytest.mark.llm`) |
| `equipment_scarce.yaml` | Limited WFP inventory → careful allocation |
| `infeasible.yaml` | Over capacity → `needs_human_review`, deferred jobs allowed |

## Assertions (per scenario)

- Final `schedule_runs.status` matches `expect.status`
- `iteration_count` ≤ orchestrator `max_iterations`
- If `expect.status: approved`, approval within `expect.max_iterations`
- No critic `structured_issues` with severity `high` or `critical` (unless `max_high_severity_issues: 999`)
- Every seeded job is in `assigned_job_ids` or `unassigned_job_ids` on the final attempt

On failure, pytest prints `langfuse_trace_id` when Langfuse is configured.

## Run (Supabase — default)

```bash
# .env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
PYTHONPATH=backend python3 -m pytest tests/e2e/test_orchestrator_e2e.py -v -m "e2e and not llm"
```

## Run LLM scenarios

```bash
export ANTHROPIC_API_KEY=...
export RUN_LLM_E2E=1   # required in CI
PYTHONPATH=backend python3 -m pytest tests/e2e/test_orchestrator_e2e.py -v -m llm
```

## Optional local PostGIS (schema only)

For migration smoke tests without touching remote data:

```bash
docker compose -f docker/docker-compose.e2e.yml up -d
export E2E_DATABASE_URL=postgresql://postgres:e2e@localhost:5433/production_agent_e2e
bash scripts/e2e_apply_migrations.sh
```

Orchestrator E2E still uses Supabase REST (`tools_db`) for the mission; Docker Postgres is for schema validation and future local-stack work.

## Eval harness (quality over time)

Repeated runs for regression tracking (not pass/fail):

```bash
python -m evals.run --scenario all --iterations 5
python -m evals.run --scenario simple_week --iterations 3 --no-agent
```

Writes:

- Markdown report: `evals/reports/{timestamp}.md` (summary table + per-trial detail)
- Raw rows: Supabase `eval_runs` (apply migration `20250524170000_eval_runs.sql`)

Metrics per scenario: approval rate within iteration cap, mean/variance of iterations, total drive minutes, and preference violations.

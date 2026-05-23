# Phase 6 — Orchestrator loop

Anthropic Messages API tool-use loop wired to Phase 4 tools and the Phase 5 critic. Each run is logged to **Langfuse** (optional) and **`schedule_runs` / `schedule_run_iterations`** in Supabase.

## Iteration pattern

The system prompt enforces this sequence per iteration (max 4 by default):

1. **Build constraints** — `get_crew_availability`, `get_weather`, `check_equipment`, optional `get_travel_matrix` / `get_customer_history`
2. **Optimize** — `run_optimizer`
3. **Save** — `save_schedule_attempt`
4. **Critique** — `critique_schedule` (deterministic + optional LLM critic)

**Outcomes:**

| Critic | Iterations left | Action |
|--------|-----------------|--------|
| Approved | any | Finalize run (`status=approved`) |
| Rejected | &lt; max | Inject `feedback_prompt` into next iteration user message |
| Rejected | max reached | `status=needs_human_review`, keep `best_schedule_attempt_id` by fill score |

## Execution modes

| Mode | When | Behavior |
|------|------|----------|
| **Agent** | `use_agent=True` (default) + `ANTHROPIC_API_KEY` | Claude tool-use loop via `anthropic` SDK |
| **Programmatic** | `use_agent=False` | Fixed tool order for CI / no API key |

## API

```python
from app.orchestrator import run_scheduling_mission
from app.orchestrator.schemas import ScheduleWeekInput

result = run_scheduling_mission(
    ScheduleWeekInput(
        user_request="Schedule next week's jobs.",
        use_llm_critic=False,   # rule critic in CI
        use_agent=True,         # False for programmatic path
        max_iterations=4,
    )
)
# result.schedule_run_id, .status, .iterations, .langfuse_trace_id
```

## Database

Migration: `supabase/migrations/20250524130000_schedule_runs.sql`

- **`schedule_runs`** — one row per mission (`user_request`, week bounds, `status`, `langfuse_trace_id`, `best_schedule_attempt_id`)
- **`schedule_run_iterations`** — per-iteration audit (`approved`, `feedback_prompt`, `issues`, FKs to attempt + critic_feedback)

## Environment

```bash
ANTHROPIC_API_KEY=...              # required for agent mode
ANTHROPIC_MODEL=claude-sonnet-4-20250514
ORCHESTRATOR_MAX_ITERATIONS=4      # optional override

LANGFUSE_PUBLIC_KEY=...            # optional tracing
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```

## Verify

```bash
# CI-friendly (no Anthropic)
PYTHONPATH=backend python3 -m pytest tests/test_orchestrator.py::test_orchestrator_programmatic_without_anthropic -v

# Full suite (Anthropic E2E skipped on 429)
PYTHONPATH=backend python3 -m pytest tests/test_orchestrator.py -v

# Manual mission
PYTHONPATH=backend python3 scripts/run_orchestrator.py
# Add --no-agent to skip Claude
```

**Supabase:** query `schedule_runs` and `schedule_run_iterations` for the printed `schedule_run_id`.

**Langfuse:** open trace id from `langfuse_trace_id` when keys are set.

## Layout

```
backend/app/orchestrator/
  runner.py          # mission loop, Langfuse, Supabase logging
  tool_dispatch.py   # tool schemas + execute_tool
  prompts.py         # SYSTEM_PROMPT
  context.py         # shared state across tools
  schemas.py         # ScheduleWeekInput, ScheduleRunResult
scripts/run_orchestrator.py
```

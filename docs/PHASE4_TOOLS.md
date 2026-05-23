# Phase 4 — Tool wrappers

Typed functions the orchestrator will call. All use **Pydantic** I/O and **supabase-py** for reads/writes.

## Tools

| Function | Purpose |
|----------|---------|
| `get_weather` | Forecast windows; cached in `weather_cache` |
| `get_crew_availability` | Crew shifts for a date (`crew_availability` overrides + defaults) |
| `get_customer_history` | `service_history` for a client |
| `get_travel_matrix` | N×N minutes; cached in `travel_matrix_cache` |
| `run_optimizer` | Loads DB → travel matrix → OR-Tools |
| `check_equipment` | Inventory + crew gear vs job requirements |
| `save_schedule_attempt` | Audit row in `schedule_attempts` |
| `get_previous_critic_feedback` | `critic_feedback` + `plan_reviews` |

## API keys (optional)

In `.env`:

```bash
GOOGLE_MAPS_API_KEY=...   # else haversine estimate
TOMORROW_IO_API_KEY=...   # else mock weather
```

## Migrations

```bash
supabase db push   # 20250524110000_phase4_tool_support.sql
                   # 20250524110001_phase4_tool_rls.sql
```

## Usage

```python
from datetime import date
from app.tools import get_weather, run_optimizer, save_schedule_attempt
from app.tools.schemas import GetWeatherInput, RunOptimizerInput, SaveScheduleAttemptInput

get_weather(GetWeatherInput(lat=45.5, lng=-73.57, forecast_date=date.today()))

opt = run_optimizer(RunOptimizerInput(
    target_date=date.today(),
    job_ids=["job-1", "job-2"],
    crew_ids=["crew-a"],
))
save_schedule_attempt(SaveScheduleAttemptInput(
    target_date=date.today(),
    job_ids=["job-1", "job-2"],
    crew_ids=["crew-a"],
    result=opt.result,
    optimizer_input=opt.optimizer_input,
))
```

## Verify

```bash
pytest tests/test_tools.py -v
python scripts/test_tools.py
```

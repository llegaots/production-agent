# Phase 5 — Critic agent

Two-layer schedule review before client messaging.

## Architecture

```
Schedule + context
       │
       ▼
┌──────────────────────┐
│ Deterministic checker │  drive min/crew-day, geographic spread,
│                       │  preference violations, week-fill, equipment-fit
└──────────┬───────────┘
           │ metrics + flags
           ▼
┌──────────────────────┐
│ LLM critic (Claude)   │  → { approved, issues[], feedback_prompt }
│ or rule fallback      │
└──────────┬───────────┘
           ▼
    critic_feedback (Supabase)
```

## API

```python
from app.critic import review_schedule
from app.critic.schemas import ReviewScheduleInput

out = review_schedule(ReviewScheduleInput(
    target_date=date.today(),
    optimizer_input=opt.optimizer_input,
    optimizer_result=opt.result,
    schedule_attempt_id=attempt_id,  # optional — loads prior reviews
    persist=True,
    use_llm=False,   # True when ANTHROPIC_API_KEY set
))
# out.metrics — DeterministicMetrics
# out.verdict.approved, .issues, .feedback_prompt
# out.critic_feedback_id — when persist=True
```

## Deterministic metrics

| Metric | Meaning |
|--------|---------|
| `crew_days[].drive_minutes` | Total travel per crew route |
| `crew_days[].geographic_spread_km` | Stddev of job coordinates (km) |
| `preference_violation_count` | Jobs not on `preferred_crew_id` |
| `week_fill_score` | Assigned jobs ÷ input jobs |
| `equipment_fit_score` | Assignments with crew carrying required gear |

Default flags: spread > 12 km, fill < 85%, equipment < 95%, preference violations, excessive drive ratio.

## Environment

```bash
ANTHROPIC_API_KEY=...          # optional — enables LLM layer
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

Without the key, the **rule-based critic** uses the same thresholds (used in CI).

## Migration

`supabase/migrations/20250524120000_critic_feedback_metrics.sql` adds `metrics`, `feedback_prompt`, `issues` columns.

## Verify

```bash
pytest tests/test_critic.py -v
python scripts/test_critic.py
```

Expected: good schedule **approved**; bad schedules **rejected** with specific `issues` and `feedback_prompt`.

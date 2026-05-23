# Phase 7 — Specialists (intake + client messenger)

Natural-language intake becomes a structured **job** in Supabase; the **client messenger** drafts a notification stored in `client_messages` with `status=draft` (not sent).

## Flow

```
"Schedule a recurring service for Mrs. Chen, Tuesdays"
        │
        ▼
┌─────────────────┐
│ Intake parser    │  rule or Anthropic → StructuredJobDraft
└────────┬────────┘
         │ resolve client (Mrs. Chen), insert jobs + intake_requests
         ▼
┌─────────────────┐
│ Client messenger │  rule or Anthropic → subject + body + guardrails
└────────┬────────┘
         │ insert client_messages (status=draft)
         ▼
    Draft ready for dispatcher review
```

## API

```python
from app.specialists import run_intake_to_draft_flow
from app.specialists.schemas import IntakeToDraftInput

result = run_intake_to_draft_flow(
    IntakeToDraftInput(
        raw_text="Schedule a recurring service for Mrs. Chen, Tuesdays",
        use_llm_intake=False,
        use_llm_messenger=False,
    )
)
# result.intake.job_id, result.message.client_message_id
```

## Tables

| Table | Purpose |
|-------|---------|
| `intake_requests` | Raw text + parsed JSON + links to client/job |
| `jobs.recurrence_rule`, `jobs.preferred_day_of_week` | Recurring weekday from intake |
| `client_messages` | Draft body, score, guardrails, `status=draft` |

Migration: `supabase/migrations/20250524140000_phase7_specialists.sql`

## Verify

```bash
PYTHONPATH=backend python3 scripts/test_specialists_flow.py
PYTHONPATH=backend python3 -m pytest tests/test_specialists.py -v
```

Expected: job for Mrs. Chen with `preferred_day_of_week=1` (Tuesday), draft message mentioning Tuesdays, `client_messages.status=draft`.

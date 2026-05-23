# Phase 8 — Chat API

Dispatcher chat with SSE streaming, scheduling orchestrator tool, and schedule approve/reject.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat/sessions` | Create session |
| `POST` | `/chat/sessions/{id}/messages` | User message → **SSE** stream |
| `GET` | `/chat/sessions/{id}/messages` | List persisted history |
| `POST` | `/schedules/{id}/approve` | Approve a `schedule_runs` row |
| `POST` | `/schedules/{id}/reject` | Reject a schedule run |

## SSE events

| Event | Payload |
|-------|---------|
| `text_delta` | `{ "text": "..." }` |
| `tool_call` | `{ "id", "name", "input" }` |
| `tool_result` | `{ "tool_use_id", "result" }` |
| `schedule_preview` | Structured jsonb for UI (routes, jobs, status) |
| `message_complete` | `{ "message_id", "role" }` |
| `error` | `{ "message", "fallback" }` |

## Orchestrator tool

The chat agent exposes `run_scheduling_orchestrator`, which calls `run_scheduling_mission` (Phase 6). Set `"use_orchestrator_agent": false` in the message body to use the programmatic tool path (CI-friendly).

## Persistence

- `chat_sessions` — conversation metadata
- `chat_messages` — full history including `tool_calls`, `schedule_preview`, `schedule_run_id`

Migration: `supabase/migrations/20250524150000_chat_api.sql`

## Verify

```bash
cd backend && uvicorn app.main:app --reload --port 8000
# other terminal:
bash scripts/test_chat_curl.sh

PYTHONPATH=backend python3 -m pytest tests/test_chat_api.py -v
```

Query Supabase:

```sql
SELECT role, content, schedule_preview IS NOT NULL AS has_preview
FROM chat_messages
WHERE session_id = '<session_id>'
ORDER BY sequence_number;
```

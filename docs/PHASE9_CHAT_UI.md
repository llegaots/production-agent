# Phase 9 — Dispatcher Chat UI

Next.js 15 + shadcn/ui + supabase-js. **All business data is read from Supabase** (with Realtime reloads). **No localStorage.** Session selection uses the URL (`/chat/[sessionId]`).

## Stack

| Layer | Tech |
|-------|------|
| UI | Next.js App Router, Tailwind, shadcn/ui |
| Auth | Supabase Auth (`@supabase/ssr`) |
| Data | supabase-js queries + Realtime `postgres_changes` |
| Streaming send | FastAPI SSE (`POST /chat/sessions/{id}/messages`) |
| Approve/reject | FastAPI `POST /schedules/{id}/approve|reject` |

## Features

- **Session sidebar** — lists `chat_sessions`, ordered by `updated_at` (Realtime)
- **Chat window** — messages from `chat_messages` (Realtime); SSE only for in-flight text
- **Schedule preview** — renders `schedule_preview` jsonb as crew × day table (jobs, times, drive segments)
- **Critic warnings** — `issues[]` alert on preview card
- **Approve / Reject** — inline on preview messages
- **Iteration progress** — live `schedule_run_iterations` + `schedule_runs` while orchestrator runs

## Setup

1. Apply migration `20250524160000_phase9_realtime.sql` (Realtime publication + auth RLS).

2. Create a dispatcher user in Supabase Dashboard → Authentication → Users.

3. Copy `frontend/.env.local.example` → `frontend/.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://127.0.0.1:8010
```

4. Run API + UI:

```bash
cd backend && PYTHONPATH=. uvicorn app.main:app --port 8010
cd frontend && npm run dev
```

Open http://localhost:3000 → sign in → create chat → *"Schedule next week's jobs"*.

## Architecture note

React state holds a **synchronized view** of Supabase rows, refreshed on every Realtime event. The only ephemeral UI state is the SSE `text_delta` buffer while a reply streams.

## Verify

- Sidebar updates when a new session is inserted
- Sending a scheduling message shows iteration rows appearing live in `schedule_run_iterations`
- Assistant message gains `schedule_preview` jsonb; table renders crews/routes
- Approve updates `schedule_runs.status` via API; Realtime refreshes the card

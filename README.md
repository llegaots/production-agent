# Production Agent

Agentic AI production manager for window cleaning companies: scheduling, crew assignment, weather/equipment constraints, and client messaging.

## Architecture (target)

- **Orchestrator** — Claude (Anthropic SDK + tool use)
- **Scheduler** — Google OR-Tools VRP (deterministic)
- **Specialists** — intake parser, plan reviewer, client messenger (LLM)
- **Data** — Supabase (Postgres + PostGIS), weather, maps, customer history

## Repo layout (Phase 1)

```
production-agent/
├── backend/                 # FastAPI application
│   └── app/
│       ├── main.py          # App entry
│       ├── config.py        # Pydantic settings
│       ├── db/              # Postgres + supabase-py clients
│       ├── optimizer/       # OR-Tools VRP (Phase 3, no DB)
│       └── routers/         # HTTP routes
├── supabase/
│   ├── config.toml          # Supabase CLI config
│   └── migrations/          # Versioned SQL (db push)
├── scripts/
│   └── verify_connections.py
├── docs/
│   └── SETUP_SUPABASE.md    # Dashboard + CLI setup
├── requirements.txt
└── .env.example
```

## Quick start (Phase 1)

1. Create a Supabase project and configure `.env` — see [docs/SETUP_SUPABASE.md](docs/SETUP_SUPABASE.md).
2. `pip install -r requirements.txt`
3. `supabase link` + `supabase db push` (PostGIS migration)
4. `python scripts/verify_connections.py`
5. `cd backend && uvicorn app.main:app --reload --port 8000`

## Build phases

| Phase | Status |
|-------|--------|
| 1 — Scaffolding | Done |
| 2 — Data models | Done |
| 3 — OR-Tools optimizer | Done (verify) |
| 4 — Tool wrappers | Pending |
| 5 — Orchestrator | Pending |
| 6 — Specialists | Pending |
| 7 — REST API | Pending |
| 8 — Dispatcher UI | Pending |

## License

Private / TBD

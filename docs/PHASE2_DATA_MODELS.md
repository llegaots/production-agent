# Phase 2 — Data models

## Schema

| Product name | DB object | Notes |
|--------------|-----------|--------|
| customers | `clients` table + `customers` view | View aliases email/phone columns |
| crews | `crews` | `skills[]` denormalized; `crew_skills` normalized |
| equipment | `equipment` | Inventory counts |
| crew_skills | `crew_skills` | `(crew_id, skill)` PK |
| jobs | `jobs` | PostGIS `location` generated from lat/lng |
| service_history | `service_history` | Completed visit log |

Scheduling tables (`plans`, `crew_days`, `scheduled_stops`) are included for later phases.

## Migrations (repo)

```
supabase/migrations/
  20250523190000_enable_postgis.sql
  20250524100000_init_core_schema.sql
  20250524100001_crew_skills_and_service_history.sql
  20250524100002_rls_policies.sql
```

Apply to your linked project:

```bash
supabase login
supabase link --project-ref awwcdqwdwrtbmkplpkup
supabase db push
```

Your **PRODUCTION AGENT** project may already have core tables from earlier work; newer migrations are idempotent (`IF NOT EXISTS`).

## RLS

- **authenticated** — full read/write on ops tables (dispatcher UI in Phase 8).
- **anon** — read `clients`; read `jobs` only when `scheduled` or `confirmed`.
- **service_role** (backend) — bypasses RLS.

## Seed data

Idempotent seed prefixed with `seed-` (does not touch Clearview demo rows):

```bash
python scripts/seed.py          # skip if seed clients exist
python scripts/seed.py --force  # replace seed-* rows only
```

Targets: 20 clients, 4 crews, 50 pending jobs, equipment links, `crew_skills` rows.

## Verify

```bash
python scripts/test_queries.py
# or API:
cd backend && uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/data/summary
curl http://localhost:8000/data/jobs/pending?limit=10
```

## Python layout

- `backend/app/models/schemas.py` — Pydantic types
- `backend/app/repositories/operations.py` — supabase-py queries
- `backend/app/routers/data.py` — REST smoke endpoints

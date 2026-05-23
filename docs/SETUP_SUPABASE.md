# Supabase setup (Phase 1)

Follow these steps once to create your cloud project and wire it to this repo.

## 1. Supabase project

**Your project:** `PRODUCTION AGENT` — ref `awwcdqwdwrtbmkplpkup` (us-west-2).

If you are setting up from scratch:

1. Go to [https://supabase.com/dashboard](https://supabase.com/dashboard) and sign in.
2. **New project** → name (e.g. `production-agent`), database password, region.
3. Wait until status is **Active**.

Save the database password — you need it for `SUPABASE_DB_URL`.

## 2. Collect credentials

In **Project Settings**:

| Setting | Where | Env var |
|--------|--------|---------|
| Project URL | **API** → Project URL | `SUPABASE_URL` |
| Service role key | **API** → `service_role` (secret) | `SUPABASE_SERVICE_KEY` |
| Direct connection string | **Database** → Connection string → **URI** (not Transaction pooler) | `SUPABASE_DB_URL` |

Use the **direct** connection host (`db.<ref>.supabase.co`), not the pooler, for migrations and `psycopg`.

Example `.env` (copy from `.env.example`):

```bash
SUPABASE_URL=https://abcdefghijklmnop.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_DB_URL=postgresql://postgres:YOUR_DB_PASSWORD@db.abcdefghijklmnop.supabase.co:5432/postgres
```

**Security:** Never commit `.env` or expose `SUPABASE_SERVICE_KEY` in a browser or Next.js `NEXT_PUBLIC_*` vars.

## 3. Link the Supabase CLI to your project

From the repo root (requires [Supabase CLI](https://supabase.com/docs/guides/cli)):

```bash
supabase login
supabase link --project-ref YOUR_PROJECT_REF
```

`YOUR_PROJECT_REF` is the subdomain in your project URL (e.g. `abcdefghijklmnop`).

## 4. Enable PostGIS (migration)

This repo includes a versioned migration:

`supabase/migrations/20250523190000_enable_postgis.sql`

Apply it to your remote database:

```bash
supabase db push
```

Alternatively, run once in the dashboard **SQL Editor**:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

## 5. Install Python deps and verify

```bash
cd /path/to/production-agent
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your values

python scripts/verify_connections.py
```

Expected output: both checks print `OK`.

## 6. Run the API

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) and try:

- `GET /` — hello payload
- `GET /health` — liveness
- `GET /health/postgres` — direct Postgres
- `GET /health/supabase` — Supabase REST + client
- `GET /health/all` — both

## Troubleshooting

| Symptom | Likely fix |
|--------|------------|
| `password authentication failed` | Wrong password in `SUPABASE_DB_URL`; reset in Database settings if needed |
| SSL / connection timeout | Use direct `db.*.supabase.co` URI; allow your IP under **Database** → network if restricted |
| PostgREST 401 | Wrong or truncated `SUPABASE_SERVICE_KEY` |
| `postgis_enabled: false` | Run `supabase db push` or the SQL above |

When both health checks pass, reply **go** to continue to **Phase 2 — Data models**.

## Cloud Agent / remote VM note

`.env` is gitignored and **does not sync** to the cloud VM automatically. If you created `.env` only on your laptop:

1. Save the same file as `/workspace/.env` in the agent workspace (or paste keys into **Cloud Agent secrets** as `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_URL`).
2. Run `python scripts/check_env.py` then `python scripts/verify_connections.py`.

**Already done on your `PRODUCTION AGENT` project (via dashboard MCP):** PostGIS extension enabled (`postgis` 3.3.7).

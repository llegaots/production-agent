#!/usr/bin/env bash
# Apply repo migrations to isolated E2E Postgres (docker/docker-compose.e2e.yml).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${E2E_DATABASE_URL:-postgresql://postgres:e2e@localhost:5433/production_agent_e2e}"

echo "Applying migrations to E2E database..."
for f in "$ROOT"/supabase/migrations/*.sql; do
  echo "  -> $(basename "$f")"
  psql "$URL" -v ON_ERROR_STOP=1 -f "$f" >/dev/null
done
echo "Done."

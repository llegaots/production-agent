#!/usr/bin/env python3
"""
Standalone connection verifier (no server required).

Usage (from repo root, with .venv activated):
  python scripts/verify_connections.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `from app...` when run from repo root.
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    try:
        from app.config import get_settings
        from app.db.postgres import check_postgres_connection
        from app.db.supabase_client import check_supabase_connection
    except Exception as exc:
        print(f"FAIL: Could not load settings — {exc}")
        print("Copy .env.example to .env and set SUPABASE_* variables.")
        return 1

    settings = get_settings()
    exit_code = 0

    if not settings.supabase_db_url:
        print("Skipping Postgres (SUPABASE_DB_URL not set).")
    else:
        print("Checking direct Postgres (SUPABASE_DB_URL)...")
        try:
            pg = check_postgres_connection(settings)
            print(f"  OK — db={pg['database']}, postgis={pg['postgis_enabled']}")
        except Exception as exc:
            print(f"  FAIL — {exc}")
            exit_code = 1

    print("Checking Supabase API (SUPABASE_URL + SUPABASE_SERVICE_KEY)...")
    try:
        sb = check_supabase_connection(settings)
        print(f"  OK — rest_status={sb['rest_api_status']}")
    except Exception as exc:
        print(f"  FAIL — {exc}")
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

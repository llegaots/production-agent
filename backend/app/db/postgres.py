from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row

from app.config import Settings


@contextmanager
def postgres_connection(settings: Settings) -> Generator[psycopg.Connection, None, None]:
    """Open a direct Postgres connection (migrations, advisors, raw SQL)."""
    conn = psycopg.connect(str(settings.supabase_db_url), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def check_postgres_connection(settings: Settings) -> dict[str, Any]:
    """
    Verify direct Postgres connectivity and report server metadata.
    Used by health checks and the standalone verify script.
    """
    with postgres_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    version() AS postgres_version,
                    current_database() AS database,
                    current_user AS db_user
                """
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'postgis') AS postgis_enabled"
            )
            postgis = cur.fetchone()

    return {
        "ok": True,
        "postgres_version": row["postgres_version"] if row else None,
        "database": row["database"] if row else None,
        "db_user": row["db_user"] if row else None,
        "postgis_enabled": bool(postgis and postgis.get("postgis_enabled")),
    }

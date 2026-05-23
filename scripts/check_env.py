#!/usr/bin/env python3
"""Verify .env exists and required keys are set (values are not printed)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
REQUIRED = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
OPTIONAL_FOR_POSTGRES = ("SUPABASE_DB_URL",)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def main() -> int:
    if not ENV_PATH.is_file():
        print(f"Missing {ENV_PATH}")
        print("Save your Supabase keys to /workspace/.env (gitignored).")
        return 1

    env = load_env_file(ENV_PATH)
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        print(f".env is missing: {', '.join(missing)}")
        return 1

    ref = "awwcdqwdwrtbmkplpkup"
    url = env["SUPABASE_URL"]
    if ref not in url:
        print(f"Warning: SUPABASE_URL does not contain project ref {ref}")

    missing_db = [k for k in OPTIONAL_FOR_POSTGRES if not env.get(k)]
    print(f"OK — .env found with {len(REQUIRED)} required keys (values hidden).")
    if missing_db:
        print(f"Note: missing {', '.join(missing_db)} — Postgres health check will not run.")
    else:
        print("Run: python scripts/verify_connections.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

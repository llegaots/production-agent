#!/usr/bin/env python3
"""Verify .env exists, required keys are set, and every key is recognized by Settings."""
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

    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings, known_env_var_names

    env = load_env_file(ENV_PATH)
    known = known_env_var_names()
    unrecognized = sorted(k for k in env if k not in known)
    missing = [k for k in REQUIRED if not env.get(k)]

    if missing:
        print(f".env is missing required keys: {', '.join(missing)}")
        return 1

    if unrecognized:
        print("Unrecognized .env keys (ignored by app Settings):")
        for key in unrecognized:
            print(f"  - {key}")
        return 1

    # Load Settings to confirm pydantic accepts the file (values not printed).
    Settings()

    ref = "awwcdqwdwrtbmkplpkup"
    url = env["SUPABASE_URL"]
    if ref not in url:
        print(f"Warning: SUPABASE_URL does not contain project ref {ref}")

    missing_db = [k for k in OPTIONAL_FOR_POSTGRES if not env.get(k)]
    print(f"OK — .env has {len(env)} keys; all {len(known)} Settings env names are supported.")
    print(f"Loaded {len(REQUIRED)} required keys (values hidden).")
    if missing_db:
        print(f"Note: missing {', '.join(missing_db)} — Postgres health check will not run.")
    else:
        print("Run: python scripts/verify_connections.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

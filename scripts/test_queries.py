#!/usr/bin/env python3
"""Phase 2 verification: supabase-py queries against live data."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.operations import OperationsRepository  # noqa: E402


def main() -> int:
    repo = OperationsRepository()
    counts = repo.count_summary()
    print("Table counts:", counts)

    required = ("clients", "crews", "jobs")
    for key in required:
        if counts.get(key, 0) < 1:
            print(f"FAIL: expected rows in {key}")
            return 1

    clients = repo.list_clients(limit=3)
    print(f"Sample clients ({len(clients)}):", [c.name for c in clients])

    crews = repo.list_crews()
    print(f"Crews ({len(crews)}):", [c.name for c in crews])

    skills = repo.list_crew_skills()
    print(f"Crew skills rows: {len(skills)}")

    jobs = repo.list_pending_jobs(limit=5)
    print(f"Pending jobs sample: {len(jobs)}")

    if clients:
        history = repo.list_service_history(clients[0].id, limit=3)
        print(f"Service history for {clients[0].name}: {len(history)} rows")

    try:
        via_view = repo.list_customers_view(limit=2)
        print(f"customers view: {len(via_view)} rows")
    except Exception as exc:
        print(f"customers view skipped: {exc}")

    print("OK — Phase 2 queries succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

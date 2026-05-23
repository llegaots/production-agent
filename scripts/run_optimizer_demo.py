#!/usr/bin/env python3
"""Run hardcoded optimizer scenarios (Phase 3 smoke test)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.optimizer import solve
from app.optimizer.exceptions import InfeasibleScheduleError
from app.optimizer.scenarios import (
    feasible_two_crew_scenario,
    infeasible_skills_scenario,
)


def _print_result(label: str, result) -> None:
    print(f"\n=== {label} ===")
    print(f"status: {result.status}")
    if result.messages:
        print("messages:", result.messages)
    print("unassigned:", result.unassigned_job_ids)
    for route in result.routes:
        if not route.stops:
            continue
        stops = [f"{s.job_id}@{s.arrival_minute}" for s in route.stops]
        print(f"  {route.crew_id}: {' -> '.join(stops)} (end {route.end_minute})")


def main() -> int:
    ok = solve(feasible_two_crew_scenario())
    _print_result("Feasible (2 crews, 4 jobs)", ok)

    bad = solve(infeasible_skills_scenario())
    _print_result("Infeasible skills", bad)

    try:
        solve(infeasible_skills_scenario(), strict=True)
    except InfeasibleScheduleError as exc:
        print("\n=== Strict mode ===")
        print("InfeasibleScheduleError:", exc)

    print("\nJSON snippet:", json.dumps(ok.model_dump(), indent=2)[:500], "...")
    return 0 if ok.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())

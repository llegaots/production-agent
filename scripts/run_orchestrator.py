#!/usr/bin/env python3
"""Run orchestrator: 'schedule next week's jobs'."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.orchestrator import run_scheduling_mission
from app.orchestrator.schemas import ScheduleWeekInput


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scheduling orchestrator mission")
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="Deterministic tool sequence (no Anthropic API)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Override ORCHESTRATOR_MAX_ITERATIONS",
    )
    args = parser.parse_args()

    result = run_scheduling_mission(
        ScheduleWeekInput(
            user_request="Schedule next week's jobs for all pending work in the window.",
            use_llm_critic=False,
            use_agent=not args.no_agent,
            max_iterations=args.max_iterations,
        )
    )
    print("schedule_run_id:", result.schedule_run_id)
    print("status:", result.status, "approved:", result.approved)
    print("iterations:", len(result.iterations))
    for it in result.iterations:
        print(
            f"  iter {it.iteration_number}: approved={it.approved} "
            f"attempt={it.schedule_attempt_id} issues={it.issues[:2]}"
        )
    print("langfuse_trace_id:", result.langfuse_trace_id)
    print("summary:", result.summary[:300])
    return 0 if result.approved or result.needs_human_review else 1


if __name__ == "__main__":
    raise SystemExit(main())

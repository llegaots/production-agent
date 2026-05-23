#!/usr/bin/env python3
"""Smoke test: critic agent on good vs bad schedules."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.critic.review import review_schedule
from app.critic.scenarios import (
    bad_review_input_geographic_spray,
    bad_review_input_preference_violations,
    good_review_input,
)


def _print_review(label: str, out) -> None:
    print(f"\n=== {label} ===")
    print("approved:", out.verdict.approved)
    print("issues:", out.verdict.issues)
    print("feedback:", out.verdict.feedback_prompt[:200], "...")
    print(
        "metrics: fill=",
        out.metrics.week_fill_score,
        "equip=",
        out.metrics.equipment_fit_score,
        "pref_viol=",
        out.metrics.preference_violation_count,
    )


def main() -> int:
    good = review_schedule(good_review_input())
    _print_review("Good schedule", good)

    bad = review_schedule(bad_review_input_preference_violations())
    _print_review("Bad (preference violations)", bad)

    spray = review_schedule(bad_review_input_geographic_spray())
    _print_review("Bad (geographic spray)", spray)

    if good.verdict.approved and not bad.verdict.approved and not spray.verdict.approved:
        print("\nOK — critic distinguishes good vs bad schedules.")
        return 0
    print("\nFAIL — unexpected approve/reject pattern")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

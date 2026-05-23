#!/usr/bin/env python3
"""Phase 7 E2E: intake → job → drafted client message."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.specialists import run_intake_to_draft_flow
from app.specialists.schemas import IntakeToDraftInput

DEFAULT_TEXT = "Schedule a recurring service for Mrs. Chen, Tuesdays"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?", default=DEFAULT_TEXT)
    parser.add_argument("--llm", action="store_true", help="Use Anthropic for parse/draft")
    args = parser.parse_args()

    result = run_intake_to_draft_flow(
        IntakeToDraftInput(
            raw_text=args.text,
            use_llm_intake=args.llm,
            use_llm_messenger=args.llm,
        )
    )

    print("intake_request_id:", result.intake.intake_request_id)
    print("job_id:", result.intake.job_id)
    print("client_id:", result.intake.client_id, "parser:", result.intake.parser_mode)
    print("recurrence:", result.intake.draft.recurrence_rule)
    print("preferred_day:", result.intake.draft.preferred_day_of_week)
    print("client_message_id:", result.message.client_message_id)
    print("status:", result.message.status, "(not sent)")
    print("subject:", result.message.draft.subject)
    print("--- draft body ---")
    print(result.message.draft.body)
    print("---")
    print("guardrails:", "passed" if result.message.draft.guardrail_passed else "FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

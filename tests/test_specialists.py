"""Phase 7 specialists tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

pytestmark = pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") and not (ROOT / ".env").is_file(),
    reason="Supabase required",
)

CHEN_REQUEST = "Schedule a recurring service for Mrs. Chen, Tuesdays"


def test_intake_rule_parser():
    from app.specialists.intake.parse import parse_intake_request
    from app.specialists.schemas import IntakeParseInput

    draft, mode = parse_intake_request(
        IntakeParseInput(raw_text=CHEN_REQUEST, use_llm=False)
    )
    assert mode == "rule"
    assert "Chen" in draft.client_name
    assert draft.preferred_day_of_week == 1  # Tuesday
    assert "weekly" in draft.recurrence_rule.lower()


def test_full_intake_to_draft_flow():
    from app.specialists import run_intake_to_draft_flow
    from app.specialists.schemas import IntakeToDraftInput
    from app.tools._db import tools_db

    result = run_intake_to_draft_flow(
        IntakeToDraftInput(
            raw_text=CHEN_REQUEST,
            use_llm_intake=False,
            use_llm_messenger=False,
        )
    )

    assert result.intake.job_id
    assert result.intake.client_id
    assert result.message.client_message_id
    assert result.message.status == "draft"

    job = (
        tools_db()
        .table("jobs")
        .select("client_id, recurrence_rule, preferred_day_of_week, notes")
        .eq("id", result.intake.job_id)
        .single()
        .execute()
        .data
    )
    assert job["client_id"] == result.intake.client_id
    assert job["preferred_day_of_week"] == 1
    assert job["recurrence_rule"]

    client = (
        tools_db()
        .table("clients")
        .select("name")
        .eq("id", result.intake.client_id)
        .single()
        .execute()
        .data
    )
    assert "Chen" in client["name"]

    intake_row = (
        tools_db()
        .table("intake_requests")
        .select("raw_text, job_id, parser_mode")
        .eq("id", str(result.intake.intake_request_id))
        .single()
        .execute()
        .data
    )
    assert CHEN_REQUEST in intake_row["raw_text"]
    assert intake_row["job_id"] == result.intake.job_id

    msg = (
        tools_db()
        .table("client_messages")
        .select("status, message, subject, guardrail_passed, job_id")
        .eq("id", str(result.message.client_message_id))
        .single()
        .execute()
        .data
    )
    assert msg["status"] == "draft"
    assert msg["job_id"] == result.intake.job_id
    assert "Tuesday" in msg["message"] or "tuesday" in msg["message"].lower()
    assert msg["guardrail_passed"] is True
    assert len(msg["message"]) > 40

"""End-to-end: intake text → job in Supabase → drafted client message."""

from __future__ import annotations

from app.specialists.intake.persist import ensure_mrs_chen_client, parse_and_persist_intake
from app.specialists.messenger.draft import draft_client_message, persist_client_message
from app.specialists.schemas import (
    DraftMessageInput,
    IntakeParseInput,
    IntakeToDraftInput,
    IntakeToDraftResult,
)


def run_intake_to_draft_flow(inp: IntakeToDraftInput) -> IntakeToDraftResult:
    """
    Parse natural language, write job + intake_requests, draft client_messages (not sent).
    """
    ensure_mrs_chen_client()

    intake = parse_and_persist_intake(
        IntakeParseInput(
            raw_text=inp.raw_text,
            use_llm=inp.use_llm_intake,
        )
    )

    draft = draft_client_message(
        DraftMessageInput(
            job_id=intake.job_id,
            client_id=intake.client_id,
            use_llm=inp.use_llm_messenger,
        )
    )
    message = persist_client_message(
        DraftMessageInput(job_id=intake.job_id, client_id=intake.client_id),
        draft,
    )

    return IntakeToDraftResult(intake=intake, message=message)

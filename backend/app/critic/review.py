"""End-to-end schedule review pipeline."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.critic.deterministic import compute_deterministic_metrics
from app.critic.llm_critic import run_llm_critic
from app.critic.persist import persist_critic_review
from app.critic.schemas import JobCoordinate, ReviewScheduleInput, ReviewScheduleOutput
from app.tools._db import tools_db


def _load_job_coordinates(job_ids: list[str]) -> list[JobCoordinate]:
    if not job_ids:
        return []
    rows = (
        tools_db().table("jobs").select("id, lat, lng").in_("id", job_ids).execute().data or []
    )
    return [JobCoordinate(job_id=r["id"], lat=float(r["lat"]), lng=float(r["lng"])) for r in rows]


def _load_run_history(
    schedule_attempt_id: UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    if not schedule_attempt_id or limit <= 0:
        return []
    rows = (
        tools_db()
        .table("critic_feedback")
        .select("passed, issues, feedback_prompt, narrative, metrics, created_at")
        .eq("schedule_attempt_id", str(schedule_attempt_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return rows


def review_schedule(inp: ReviewScheduleInput) -> ReviewScheduleOutput:
    """
    Run deterministic metrics, LLM critic, and optionally persist to critic_feedback.
    """
    if not inp.job_coordinates:
        job_ids = list(
            dict.fromkeys(
                inp.optimizer_result.assigned_job_ids
                + inp.optimizer_result.unassigned_job_ids
            )
        )
        inp = inp.model_copy(update={"job_coordinates": _load_job_coordinates(job_ids)})

    metrics = compute_deterministic_metrics(inp)
    run_history = _load_run_history(inp.schedule_attempt_id, inp.run_history_limit)
    verdict = run_llm_critic(metrics, inp, run_history, use_llm=inp.use_llm)

    reviewer = "llm_critic" if inp.use_llm else "rule_critic"
    if inp.persist:
        out = persist_critic_review(
            schedule_attempt_id=inp.schedule_attempt_id,
            plan_id=None,
            metrics=metrics,
            verdict=verdict,
            reviewer=reviewer,
        )
        out.run_history_summary = run_history
        return out

    return ReviewScheduleOutput(
        metrics=metrics,
        verdict=verdict,
        reviewer=reviewer,
        run_history_summary=run_history,
    )

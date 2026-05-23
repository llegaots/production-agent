"""Persist critic reviews to Supabase."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.critic.schemas import CriticVerdict, DeterministicMetrics, ReviewScheduleOutput
from app.tools._db import tools_db


def persist_critic_review(
    *,
    schedule_attempt_id: UUID | None,
    plan_id: UUID | None,
    metrics: DeterministicMetrics,
    verdict: CriticVerdict,
    reviewer: str,
) -> ReviewScheduleOutput:
    score = _score_from_metrics(metrics, verdict)
    row = {
        "schedule_attempt_id": str(schedule_attempt_id) if schedule_attempt_id else None,
        "plan_id": str(plan_id) if plan_id else None,
        "reviewer": reviewer,
        "score": score,
        "passed": verdict.approved,
        "concerns": verdict.issues,
        "issues": verdict.issues,
        "narrative": verdict.feedback_prompt,
        "feedback_prompt": verdict.feedback_prompt,
        "metrics": metrics.model_dump(mode="json"),
    }
    resp = tools_db().table("critic_feedback").insert(row).execute()
    if not resp.data:
        raise RuntimeError("Failed to persist critic_feedback")
    saved = resp.data[0]
    return ReviewScheduleOutput(
        metrics=metrics,
        verdict=verdict,
        critic_feedback_id=saved["id"],
        reviewer=reviewer,
        created_at=datetime.fromisoformat(saved["created_at"].replace("Z", "+00:00")),
    )


def _score_from_metrics(metrics: DeterministicMetrics, verdict: CriticVerdict) -> int:
    if not verdict.approved:
        return max(0, 40 - len(verdict.issues) * 5)
    base = 70
    base += int(metrics.week_fill_score * 15)
    base += int(metrics.equipment_fit_score * 15)
    base -= metrics.preference_violation_count * 5
    return max(0, min(100, base))

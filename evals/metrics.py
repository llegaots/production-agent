"""Extract quantitative metrics from an orchestrator run."""

from __future__ import annotations

from dataclasses import dataclass

from app.orchestrator.schemas import ScheduleRunResult
from app.tools._db import tools_db


@dataclass(frozen=True)
class TrialMetrics:
    status: str
    approved: bool
    approved_within_cap: bool
    iteration_count: int
    iteration_cap: int
    total_drive_minutes: int
    preference_violations: int
    week_fill_score: float | None
    langfuse_trace_id: str | None
    schedule_run_id: str | None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "approved": self.approved,
            "approved_within_cap": self.approved_within_cap,
            "iteration_count": self.iteration_count,
            "iteration_cap": self.iteration_cap,
            "total_drive_minutes": self.total_drive_minutes,
            "preference_violations": self.preference_violations,
            "week_fill_score": self.week_fill_score,
            "langfuse_trace_id": self.langfuse_trace_id,
            "schedule_run_id": self.schedule_run_id,
        }


def final_attempt_id(result: ScheduleRunResult) -> str | None:
    if result.final_schedule_attempt_id:
        return str(result.final_schedule_attempt_id)
    if result.iterations:
        last = result.iterations[-1].schedule_attempt_id
        return str(last) if last else None
    return None


def _final_critic_feedback_id(result: ScheduleRunResult) -> str | None:
    if not result.iterations:
        return None
    last = result.iterations[-1].critic_feedback_id
    return str(last) if last else None


def total_drive_minutes_from_attempt(attempt_id: str) -> int:
    row = (
        tools_db()
        .table("schedule_attempts")
        .select("optimizer_result")
        .eq("id", attempt_id)
        .single()
        .execute()
        .data
    )
    opt = row.get("optimizer_result") or {}
    total = 0
    for route in opt.get("routes") or []:
        total += int(route.get("total_travel_minutes") or 0)
    return total


def critic_metrics_from_feedback(feedback_id: str) -> tuple[int, float | None]:
    row = (
        tools_db()
        .table("critic_feedback")
        .select("metrics")
        .eq("id", feedback_id)
        .single()
        .execute()
        .data
    )
    metrics = row.get("metrics") or {}
    pref = int(metrics.get("preference_violation_count") or 0)
    fill = metrics.get("week_fill_score")
    week_fill = float(fill) if fill is not None else None
    return pref, week_fill


def collect_trial_metrics(
    result: ScheduleRunResult,
    *,
    iteration_cap: int,
) -> TrialMetrics:
    attempt_id = final_attempt_id(result)
    drive = total_drive_minutes_from_attempt(attempt_id) if attempt_id else 0

    pref = 0
    week_fill: float | None = None
    feedback_id = _final_critic_feedback_id(result)
    if feedback_id:
        pref, week_fill = critic_metrics_from_feedback(feedback_id)

    approved_within_cap = bool(result.approved and result.iteration_count <= iteration_cap)

    return TrialMetrics(
        status=result.status,
        approved=bool(result.approved),
        approved_within_cap=approved_within_cap,
        iteration_count=result.iteration_count,
        iteration_cap=iteration_cap,
        total_drive_minutes=drive,
        preference_violations=pref,
        week_fill_score=week_fill,
        langfuse_trace_id=result.langfuse_trace_id,
        schedule_run_id=str(result.schedule_run_id) if result.schedule_run_id else None,
    )

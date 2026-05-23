"""Persist eval trials to Supabase eval_runs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evals.metrics import TrialMetrics


def insert_eval_run(
    db,
    *,
    eval_batch_id: UUID,
    report_path: str,
    scenario_name: str,
    trial_number: int,
    use_agent: bool,
    metrics: TrialMetrics,
) -> dict[str, Any]:
    row = {
        "eval_batch_id": str(eval_batch_id),
        "report_path": report_path,
        "scenario_name": scenario_name,
        "trial_number": trial_number,
        "schedule_run_id": metrics.schedule_run_id,
        "status": metrics.status,
        "approved": metrics.approved,
        "approved_within_cap": metrics.approved_within_cap,
        "iteration_count": metrics.iteration_count,
        "iteration_cap": metrics.iteration_cap,
        "total_drive_minutes": metrics.total_drive_minutes,
        "preference_violations": metrics.preference_violations,
        "week_fill_score": metrics.week_fill_score,
        "use_agent": use_agent,
        "langfuse_trace_id": metrics.langfuse_trace_id,
        "metrics": metrics.as_dict(),
    }
    resp = db.table("eval_runs").insert(row).execute()
    if not resp.data:
        raise RuntimeError("Failed to insert eval_runs row")
    return resp.data[0]

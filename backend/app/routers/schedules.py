"""Schedule run approve / reject endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.chat.schemas import ScheduleDecisionResponse
from app.tools._db import tools_db

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _get_run(schedule_id: UUID) -> dict:
    resp = (
        tools_db()
        .table("schedule_runs")
        .select("*")
        .eq("id", str(schedule_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Schedule run not found")
    return resp.data[0]


@router.post("/{schedule_id}/approve", response_model=ScheduleDecisionResponse)
def approve_schedule(schedule_id: UUID) -> ScheduleDecisionResponse:
    run = _get_run(schedule_id)
    if run["status"] == "approved":
        return ScheduleDecisionResponse(
            schedule_run_id=schedule_id,
            status="approved",
            approved=True,
            message="Schedule already approved.",
        )

    attempt_id = run.get("final_schedule_attempt_id") or run.get("best_schedule_attempt_id")
    now = datetime.now(timezone.utc).isoformat()
    tools_db().table("schedule_runs").update(
        {
            "status": "approved",
            "approved": True,
            "completed_at": now,
            "summary": (run.get("summary") or "") + " [Approved by dispatcher via chat API.]",
        }
    ).eq("id", str(schedule_id)).execute()

    if attempt_id:
        tools_db().table("jobs").update({"status": "scheduled"}).in_(
            "id",
            _assigned_job_ids(attempt_id),
        ).execute()

    return ScheduleDecisionResponse(
        schedule_run_id=schedule_id,
        status="approved",
        approved=True,
        message="Schedule approved and linked jobs marked scheduled.",
    )


@router.post("/{schedule_id}/reject", response_model=ScheduleDecisionResponse)
def reject_schedule(schedule_id: UUID) -> ScheduleDecisionResponse:
    run = _get_run(schedule_id)
    now = datetime.now(timezone.utc).isoformat()
    tools_db().table("schedule_runs").update(
        {
            "status": "rejected",
            "approved": False,
            "completed_at": now,
            "summary": (run.get("summary") or "") + " [Rejected by dispatcher via chat API.]",
        }
    ).eq("id", str(schedule_id)).execute()

    return ScheduleDecisionResponse(
        schedule_run_id=schedule_id,
        status="rejected",
        approved=False,
        message="Schedule rejected. Run the orchestrator again with updated constraints.",
    )


def _assigned_job_ids(attempt_id: str) -> list[str]:
    row = (
        tools_db()
        .table("schedule_attempts")
        .select("optimizer_result")
        .eq("id", attempt_id)
        .limit(1)
        .execute()
        .data
    )
    if not row:
        return []
    result = row[0].get("optimizer_result") or {}
    return list(result.get("assigned_job_ids") or [])

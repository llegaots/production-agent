"""Build schedule_preview jsonb payloads for chat UI."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.chat.schemas import SchedulePreviewPayload
from app.orchestrator.schemas import ScheduleRunResult
from app.tools._db import tools_db


def _load_attempt_optimizer_result(attempt_id: UUID | None) -> dict[str, Any]:
    if not attempt_id:
        return {}
    row = (
        tools_db()
        .table("schedule_attempts")
        .select("optimizer_result")
        .eq("id", str(attempt_id))
        .limit(1)
        .execute()
        .data
    )
    if not row:
        return {}
    return row[0].get("optimizer_result") or {}


def _assigned_job_ids_from_opt(opt: dict) -> list[str]:
    if opt.get("assigned_job_ids"):
        return list(opt["assigned_job_ids"])
    return [
        stop["job_id"]
        for route in opt.get("routes") or []
        for stop in route.get("stops") or []
        if stop.get("job_id")
    ]


def build_schedule_preview(result: ScheduleRunResult) -> SchedulePreviewPayload:
    attempt_id = result.final_schedule_attempt_id or result.best_schedule_attempt_id
    opt = _load_attempt_optimizer_result(attempt_id)
    issues: list[str] = []
    for it in result.iterations:
        issues.extend(it.issues)
    issues = list(dict.fromkeys(issues))[:20]

    return SchedulePreviewPayload(
        schedule_run_id=result.schedule_run_id,
        status=result.status,
        approved=result.approved,
        needs_human_review=result.needs_human_review,
        week_start=result.week_start.isoformat(),
        week_end=result.week_end.isoformat(),
        iteration_count=result.iteration_count,
        summary=result.summary,
        attempt_id=str(attempt_id) if attempt_id else None,
        assigned_job_ids=_assigned_job_ids_from_opt(opt),
        unassigned_job_ids=list(opt.get("unassigned_job_ids") or []),
        routes=[r for r in (opt.get("routes") or []) if r.get("stops")],
        issues=issues,
    )

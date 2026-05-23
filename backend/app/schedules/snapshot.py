"""Build and persist approved schedule snapshots."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from app.tools._db import tools_db


def _assignments_from_optimizer_result(
    optimizer_result: dict[str, Any],
    *,
    target_date: date,
) -> dict[str, dict[str, str | None]]:
    """job_id → { crew_id, day } (day ISO string; unassigned jobs omitted)."""
    out: dict[str, dict[str, str | None]] = {}
    day_str = target_date.isoformat()
    for route in optimizer_result.get("routes") or []:
        crew_id = route.get("crew_id")
        for stop in route.get("stops") or []:
            jid = stop.get("job_id")
            if jid:
                out[jid] = {"crew_id": crew_id, "day": day_str}
    return out


def _total_drive_minutes(optimizer_result: dict[str, Any]) -> int:
    total = 0
    for route in optimizer_result.get("routes") or []:
        total += int(route.get("total_travel_minutes") or 0)
    return total


def _preference_violations_from_attempt(attempt_id: str) -> int:
    rows = (
        tools_db()
        .table("critic_feedback")
        .select("metrics")
        .eq("schedule_attempt_id", attempt_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return 0
    metrics = rows[0].get("metrics") or {}
    return int(metrics.get("preference_violation_count") or 0)


def upsert_schedule_from_run(run: dict[str, Any]) -> dict[str, Any]:
    """Create or refresh schedules row from an approved schedule_run."""
    attempt_id = run.get("final_schedule_attempt_id") or run.get("best_schedule_attempt_id")
    if not attempt_id:
        raise ValueError("Schedule run has no final or best schedule attempt")

    attempt = (
        tools_db()
        .table("schedule_attempts")
        .select("*")
        .eq("id", str(attempt_id))
        .single()
        .execute()
        .data
    )
    opt = attempt.get("optimizer_result") or {}
    target = date.fromisoformat(str(attempt["target_date"]))
    assignments = _assignments_from_optimizer_result(opt, target_date=target)
    pref = _preference_violations_from_attempt(str(attempt_id))

    row = {
        "id": run["id"],
        "schedule_attempt_id": str(attempt_id),
        "week_start": run["week_start"],
        "week_end": run["week_end"],
        "target_date": target.isoformat(),
        "job_ids": list(attempt.get("job_ids") or []),
        "crew_ids": list(attempt.get("crew_ids") or []),
        "user_request": run.get("user_request") or "",
        "assignments": assignments,
        "total_drive_minutes": _total_drive_minutes(opt),
        "preference_violations": pref,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    resp = tools_db().table("schedules").upsert(row).execute()
    if not resp.data:
        raise RuntimeError("Failed to upsert schedules row")
    return resp.data[0]


def mark_schedule_golden(schedule_id: UUID) -> dict[str, Any]:
    """Mark a dispatcher-approved schedule as golden (refreshes snapshot first)."""
    run_resp = (
        tools_db()
        .table("schedule_runs")
        .select("*")
        .eq("id", str(schedule_id))
        .limit(1)
        .execute()
    )
    if not run_resp.data:
        raise ValueError(f"Schedule run not found: {schedule_id}")
    run = run_resp.data[0]
    if run["status"] != "approved" or not run.get("approved"):
        raise ValueError(
            f"Schedule {schedule_id} is not dispatcher-approved "
            f"(status={run['status']!r})"
        )

    snapshot = upsert_schedule_from_run(run)
    now = datetime.now(timezone.utc).isoformat()
    tools_db().table("schedules").update(
        {"golden": True, "golden_marked_at": now, "updated_at": now}
    ).eq("id", str(schedule_id)).execute()
    row = (
        tools_db()
        .table("schedules")
        .select("*")
        .eq("id", str(schedule_id))
        .single()
        .execute()
        .data
    )
    return row

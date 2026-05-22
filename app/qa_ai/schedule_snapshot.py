"""Rich schedule context for AI critics (operator field-of-view)."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..models import Job, PlanResult, WeekPlan
from ..storage import store


def _job_row(job: Optional[Job]) -> dict[str, Any]:
    if not job:
        return {"job_id": "unknown"}
    return {
        "job_id": job.id,
        "client_id": job.client_id,
        "service": job.service_type.value,
        "address": job.address,
        "lat": round(job.lat, 5),
        "lng": round(job.lng, 5),
        "estimated_minutes": job.estimated_minutes,
        "difficulty": job.difficulty,
        "skills": [s.value for s in job.required_skills],
        "equipment": [e.value for e in job.required_equipment],
        "earliest_date": job.earliest_date.isoformat(),
        "latest_date": job.latest_date.isoformat(),
        "status": job.status.value,
        "notes": (job.notes or "")[:200],
    }


def plan_to_operator_context(
    plan: WeekPlan,
    *,
    scheduling_mode: Optional[str] = None,
    owner_instruction: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict[str, Any]:
    """Serialize a week plan the way an ops manager scans it."""
    crews_by_id = {c.id: c for c in store.list_crews()}
    crew_days: list[dict] = []

    for cd in sorted(plan.days, key=lambda x: (x.day, x.crew_id)):
        crew = crews_by_id.get(cd.crew_id)
        stops = []
        for s in sorted(cd.stops, key=lambda x: x.order):
            job = store.get_job(s.job_id)
            stops.append(
                {
                    **_job_row(job),
                    "order": s.order,
                    "start_minute": s.start_minute,
                    "start_time": _minute_label(s.start_minute),
                    "travel_minutes_before": s.travel_minutes_before,
                    "duration_minutes": s.duration_minutes,
                }
            )
        crew_days.append(
            {
                "crew_id": cd.crew_id,
                "crew_name": crew.name if crew else cd.crew_id,
                "day": cd.day.isoformat(),
                "weekday": cd.day.strftime("%A"),
                "stops": stops,
                "total_work_minutes": cd.total_work_minutes,
                "total_drive_minutes": cd.total_drive_minutes,
                "utilization": cd.utilization,
                "overbooked": cd.overbooked,
                "warnings": cd.warnings,
            }
        )

    unscheduled = [_job_row(store.get_job(jid)) for jid in plan.unscheduled_job_ids]

    return {
        "week_start": plan.week_start.isoformat(),
        "scheduling_mode": scheduling_mode,
        "owner_instruction": owner_instruction,
        "summary": plan.summary,
        "conflicts": plan.conflicts[:15],
        "crew_days": crew_days,
        "unscheduled_jobs": unscheduled,
        "metrics": {
            "scheduled_stops": sum(len(cd.stops) for cd in plan.days),
            "crew_day_count": len(plan.days),
            "unscheduled_count": len(plan.unscheduled_job_ids),
            "overbooked_days": sum(1 for cd in plan.days if cd.overbooked),
        },
        **(extra or {}),
    }


def plan_result_context(
    result: Optional[PlanResult],
    **kwargs: Any,
) -> dict[str, Any]:
    if not result:
        return {"error": "no_plan"}
    return plan_to_operator_context(result.plan, **kwargs)


def _minute_label(mins: int, shift_start: int = 8 * 60) -> str:
    total = shift_start + mins
    h, m = divmod(total, 60)
    return f"{h:02d}:{m:02d}"

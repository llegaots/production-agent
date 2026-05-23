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
    job_lookup: Optional[dict[str, Job]] = None,
) -> dict[str, Any]:
    """Serialize a week plan the way an ops manager scans it."""
    crews_by_id = {c.id: c for c in store.list_crews()}
    crew_days: list[dict] = []

    def _resolve_job(job_id: str) -> Optional[Job]:
        if job_lookup and job_id in job_lookup:
            return job_lookup[job_id]
        return store.get_job(job_id)

    for cd in sorted(plan.days, key=lambda x: (x.day, x.crew_id)):
        crew = crews_by_id.get(cd.crew_id)
        stops = []
        for s in sorted(cd.stops, key=lambda x: x.order):
            job = _resolve_job(s.job_id)
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

    unscheduled = [_job_row(_resolve_job(jid)) for jid in plan.unscheduled_job_ids]

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
    *,
    job_lookup: Optional[dict[str, Job]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if not result:
        return {"error": "no_plan"}
    return plan_to_operator_context(result.plan, job_lookup=job_lookup, **kwargs)


def _minute_label(mins: int, shift_start: int = 8 * 60) -> str:
    total = shift_start + mins
    h, m = divmod(total, 60)
    return f"{h:02d}:{m:02d}"


def filter_qa_schedule_context(
    ctx: dict[str, Any],
    *,
    allowed_job_ids: set[str],
) -> dict[str, Any]:
    """Strip any non-qa test job IDs from schedule context sent to the critic."""
    if not allowed_job_ids:
        return ctx

    out = dict(ctx)
    crew_days = []
    for cd in ctx.get("crew_days") or []:
        stops = [s for s in cd.get("stops") or [] if s.get("job_id") in allowed_job_ids]
        if not stops:
            continue
        row = dict(cd)
        row["stops"] = stops
        crew_days.append(row)
    out["crew_days"] = crew_days

    out["unscheduled_jobs"] = [
        j for j in ctx.get("unscheduled_jobs") or [] if j.get("job_id") in allowed_job_ids
    ]
    if "metrics" in out and isinstance(out["metrics"], dict):
        m = dict(out["metrics"])
        m["scheduled_stops"] = sum(len(cd.get("stops") or []) for cd in crew_days)
        m["unscheduled_count"] = len(out["unscheduled_jobs"])
        m["crew_day_count"] = len(crew_days)
        m["overbooked_days"] = sum(1 for cd in crew_days if cd.get("overbooked"))
        out["metrics"] = m
    out["allowed_job_ids"] = sorted(allowed_job_ids)
    return out


def format_schedule_markdown(ctx: dict[str, Any]) -> str:
    """Human-readable schedule table for QA reports and handoffs."""
    if not ctx or ctx.get("error"):
        return "_No schedule produced._"

    lines: list[str] = []
    week = ctx.get("week_start")
    if week:
        lines.append(f"Week starting **{week}**")
    mode = ctx.get("scheduling_mode")
    if mode:
        lines.append(f"Mode: `{mode}`")
    if ctx.get("owner_instruction"):
        lines.append(f"Owner instruction: _{ctx['owner_instruction']}_")
    if ctx.get("summary"):
        lines.append(f"\n{ctx['summary']}\n")

    crew_days = sorted(
        ctx.get("crew_days") or [],
        key=lambda x: (x.get("day", ""), x.get("crew_id", "")),
    )
    if crew_days:
        lines.append("| Crew | Day | # | Job | Address | Time | Drive before |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for cd in crew_days:
            crew = cd.get("crew_name") or cd.get("crew_id") or "?"
            day = cd.get("weekday") or cd.get("day") or "?"
            for stop in sorted(cd.get("stops") or [], key=lambda s: s.get("order", 0)):
                addr = (stop.get("address") or "")[:40]
                lines.append(
                    f"| {crew} | {day} | {stop.get('order', '?')} | "
                    f"`{stop.get('job_id', '?')}` | {addr} | "
                    f"{stop.get('start_time', '?')} | {stop.get('travel_minutes_before', 0)}m |"
                )
            util = cd.get("utilization")
            if util is not None:
                lines.append(
                    f"| _{crew}_ | _{day}_ | | _util {round(float(util) * 100)}%_ | "
                    f"drive {cd.get('total_drive_minutes', 0)}m | | |"
                )
    else:
        lines.append("_No crew-days scheduled._")

    unscheduled = ctx.get("unscheduled_jobs") or []
    if unscheduled:
        lines.append("\n**Unscheduled:**")
        for job in unscheduled:
            lines.append(f"- `{job.get('job_id', '?')}` — {job.get('address', '')[:50]}")

    metrics = ctx.get("metrics") or {}
    if metrics:
        lines.append(
            f"\n_Stops: {metrics.get('scheduled_stops', 0)}, "
            f"unscheduled: {metrics.get('unscheduled_count', 0)}, "
            f"overbooked days: {metrics.get('overbooked_days', 0)}_"
        )

    return "\n".join(lines)

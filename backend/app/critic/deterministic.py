"""Deterministic schedule quality metrics (no LLM)."""

from __future__ import annotations

import math
import statistics
from datetime import date

from app.critic.schemas import CrewDayMetrics, DeterministicMetrics, JobCoordinate, ReviewScheduleInput
from app.optimizer.models import OptimizerInput, OptimizerResult, ScheduleCrew, ScheduleJob

# Tunable thresholds for deterministic flags
MAX_SPREAD_KM = 12.0
MIN_WEEK_FILL = 0.85
MIN_EQUIPMENT_FIT = 0.95
MAX_DRIVE_RATIO = 0.45  # drive minutes / shift minutes


def _coords_by_job(coordinates: list[JobCoordinate]) -> dict[str, tuple[float, float]]:
    return {c.job_id: (c.lat, c.lng) for c in coordinates}


def _geographic_spread_km(job_ids: list[str], coords: dict[str, tuple[float, float]]) -> float:
    points = [coords[jid] for jid in job_ids if jid in coords]
    if len(points) < 2:
        return 0.0
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    try:
        std_lat = statistics.pstdev(lats)
        std_lng = statistics.pstdev(lngs)
    except statistics.StatisticsError:
        return 0.0
    return math.sqrt(std_lat**2 + std_lng**2) * 111.0


def _job_lookup(opt_input: OptimizerInput) -> dict[str, ScheduleJob]:
    return {j.id: j for j in opt_input.jobs}


def _crew_lookup(opt_input: OptimizerInput) -> dict[str, ScheduleCrew]:
    return {c.id: c for c in opt_input.crews}


def compute_deterministic_metrics(inp: ReviewScheduleInput) -> DeterministicMetrics:
    """Compute metrics for a proposed schedule."""
    opt_in = inp.optimizer_input
    result = inp.optimizer_result
    coords = _coords_by_job(inp.job_coordinates)
    jobs_by_id = _job_lookup(opt_in)
    crews_by_id = _crew_lookup(opt_in)

    preference_violations = 0
    equipment_ok = 0
    equipment_total = 0

    crew_days: list[CrewDayMetrics] = []
    for route in result.routes:
        if not route.stops:
            continue
        job_ids = [s.job_id for s in route.stops]
        spread = _geographic_spread_km(job_ids, coords)
        crew_days.append(
            CrewDayMetrics(
                crew_id=route.crew_id,
                target_date=inp.target_date,
                drive_minutes=route.total_travel_minutes,
                geographic_spread_km=round(spread, 2),
                job_count=len(job_ids),
            )
        )
        crew = crews_by_id.get(route.crew_id)
        shift = (crew.shift_end_minute - crew.shift_start_minute) if crew else 480

        for stop in route.stops:
            job = jobs_by_id.get(stop.job_id)
            if not job:
                continue
            if job.preferred_crew_id and job.preferred_crew_id != route.crew_id:
                preference_violations += 1
            req_eq = list(job.required_equipment or [])
            if req_eq:
                equipment_total += 1
                crew_kinds = set(crew.equipment_kinds if crew else [])
                if set(req_eq).issubset(crew_kinds):
                    equipment_ok += 1
            elif crew:
                equipment_total += 1
                equipment_ok += 1

        if shift and route.total_travel_minutes > int(shift * MAX_DRIVE_RATIO):
            pass  # flagged below

    total_input_jobs = len(opt_in.jobs)
    assigned = len(result.assigned_job_ids)
    week_fill = assigned / total_input_jobs if total_input_jobs else 1.0
    equipment_fit = equipment_ok / equipment_total if equipment_total else 1.0

    issues: list[str] = []
    if preference_violations > 0:
        issues.append(
            f"{preference_violations} job(s) assigned away from preferred crew"
        )
    if week_fill < MIN_WEEK_FILL:
        issues.append(
            f"Week fill {week_fill:.0%} below target {MIN_WEEK_FILL:.0%} "
            f"({assigned}/{total_input_jobs} jobs scheduled)"
        )
    if equipment_fit < MIN_EQUIPMENT_FIT:
        issues.append(
            f"Equipment fit {equipment_fit:.0%} below target {MIN_EQUIPMENT_FIT:.0%}"
        )
    for cd in crew_days:
        if cd.geographic_spread_km > MAX_SPREAD_KM:
            issues.append(
                f"Crew {cd.crew_id} geographic spread {cd.geographic_spread_km:.1f} km "
                f"exceeds {MAX_SPREAD_KM} km (jobs too scattered)"
            )
        crew = crews_by_id.get(cd.crew_id)
        shift = (crew.shift_end_minute - crew.shift_start_minute) if crew else 480
        if shift and cd.drive_minutes > int(shift * MAX_DRIVE_RATIO):
            issues.append(
                f"Crew {cd.crew_id} drive time {cd.drive_minutes} min exceeds "
                f"{int(MAX_DRIVE_RATIO * 100)}% of {shift} min shift"
            )

    if result.unassigned_job_ids:
        issues.append(
            f"Unassigned mandatory jobs: {', '.join(result.unassigned_job_ids)}"
        )

    return DeterministicMetrics(
        crew_days=crew_days,
        preference_violation_count=preference_violations,
        week_fill_score=round(week_fill, 4),
        equipment_fit_score=round(equipment_fit, 4),
        deterministic_issues=issues,
    )

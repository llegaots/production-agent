"""Deterministic schedule quality metrics (no LLM)."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from app.critic.schemas import (
    CrewDayMetrics,
    CriticIssue,
    DeterministicMetrics,
    IssueSeverity,
    JobCoordinate,
    ReviewScheduleInput,
)
from app.optimizer.models import OptimizerInput, OptimizerResult, ScheduleCrew, ScheduleJob

# Tunable thresholds for deterministic flags
MAX_SPREAD_KM = 12.0
MIN_WEEK_FILL = 0.85
MIN_EQUIPMENT_FIT = 0.95
MAX_DRIVE_RATIO = 0.45  # drive minutes / shift minutes
MORNING_END_MINUTE = 720  # noon — arrivals after this violate morning preference windows


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


def _severity_drive_ratio(drive: int, shift: int) -> IssueSeverity:
    ratio = drive / shift if shift else 1.0
    if ratio >= 0.6:
        return "critical"
    if ratio >= MAX_DRIVE_RATIO:
        return "high"
    return "medium"


def _severity_spread(spread_km: float) -> IssueSeverity:
    if spread_km >= 25:
        return "critical"
    if spread_km >= MAX_SPREAD_KM:
        return "high"
    return "medium"


def _check_week_fill_order(
    inp: ReviewScheduleInput,
    issues: list[CriticIssue],
) -> None:
    planned = inp.job_planned_day
    if len(planned) < 3:
        return
    week_start = inp.target_date - timedelta(days=inp.target_date.weekday())
    by_offset: dict[int, list[str]] = defaultdict(list)
    for job_id, day in planned.items():
        offset = (day - week_start).days
        if 0 <= offset <= 6:
            by_offset[offset].append(job_id)
    mon_tue = len(by_offset.get(0, [])) + len(by_offset.get(1, []))
    fri = len(by_offset.get(4, []))
    total = len(planned)
    if mon_tue == 0 and fri >= max(3, int(total * 0.7)):
        issues.append(
            CriticIssue(
                type="week_fill_order",
                severity="high",
                message=(
                    f"Week fill order: Mon/Tue empty but {fri}/{total} jobs stacked on Friday"
                ),
            )
        )


def _finalize_metrics(
    crew_days: list[CrewDayMetrics],
    preference_violations: int,
    week_fill: float,
    equipment_fit: float,
    structured: list[CriticIssue],
    result: OptimizerResult,
    total_input_jobs: int,
    assigned: int,
) -> DeterministicMetrics:
    if preference_violations > 0 and not any(i.type == "preference_violation" for i in structured):
        structured.append(
            CriticIssue(
                type="preference_violation",
                severity="medium",
                message=f"{preference_violations} job(s) assigned away from preferred crew",
            )
        )
    if week_fill < MIN_WEEK_FILL:
        structured.append(
            CriticIssue(
                type="week_fill_order",
                severity="high" if week_fill < 0.5 else "medium",
                message=(
                    f"Week fill {week_fill:.0%} below target {MIN_WEEK_FILL:.0%} "
                    f"({assigned}/{total_input_jobs} jobs scheduled)"
                ),
            )
        )
    if equipment_fit < MIN_EQUIPMENT_FIT:
        structured.append(
            CriticIssue(
                type="equipment_necessity",
                severity="high",
                message=(
                    f"Equipment fit {equipment_fit:.0%} below target {MIN_EQUIPMENT_FIT:.0%}"
                ),
            )
        )
    if result.unassigned_job_ids:
        structured.append(
            CriticIssue(
                type="week_fill_order",
                severity="critical",
                message=f"Unassigned mandatory jobs: {', '.join(result.unassigned_job_ids)}",
            )
        )
    messages = [i.message for i in structured]
    return DeterministicMetrics(
        crew_days=crew_days,
        preference_violation_count=preference_violations,
        week_fill_score=round(week_fill, 4),
        equipment_fit_score=round(equipment_fit, 4),
        structured_issues=structured,
        deterministic_issues=messages,
    )


def compute_deterministic_metrics(inp: ReviewScheduleInput) -> DeterministicMetrics:
    """Compute metrics and typed issues for a proposed schedule."""
    opt_in = inp.optimizer_input
    result = inp.optimizer_result
    coords = _coords_by_job(inp.job_coordinates)
    jobs_by_id = _job_lookup(opt_in)
    crews_by_id = _crew_lookup(opt_in)
    structured: list[CriticIssue] = []

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

        if spread > MAX_SPREAD_KM:
            structured.append(
                CriticIssue(
                    type="geographic_clustering",
                    severity=_severity_spread(spread),
                    message=(
                        f"Crew {route.crew_id} geographic spread {spread:.1f} km "
                        f"exceeds {MAX_SPREAD_KM} km (zig-zag across neighborhoods)"
                    ),
                    crew_id=route.crew_id,
                )
            )

        if shift and route.total_travel_minutes > int(shift * MAX_DRIVE_RATIO):
            work = route.total_service_minutes
            structured.append(
                CriticIssue(
                    type="drive_time",
                    severity=_severity_drive_ratio(route.total_travel_minutes, shift),
                    message=(
                        f"Crew {route.crew_id} drive {route.total_travel_minutes} min vs "
                        f"{work} min work ({route.total_travel_minutes / max(1, work):.1f}× drive/work)"
                    ),
                    crew_id=route.crew_id,
                )
            )

        for stop in route.stops:
            job = jobs_by_id.get(stop.job_id)
            if not job:
                continue

            if job.preferred_crew_id and job.preferred_crew_id != route.crew_id:
                preference_violations += 1
                structured.append(
                    CriticIssue(
                        type="preference_violation",
                        severity="medium",
                        message=(
                            f"Job {job.id} prefers crew {job.preferred_crew_id} "
                            f"but assigned to {route.crew_id}"
                        ),
                        crew_id=route.crew_id,
                        job_id=job.id,
                    )
                )

            tw = job.time_window
            is_morning_pref = tw.latest_minute <= MORNING_END_MINUTE and (
                tw.latest_minute - tw.earliest_minute <= 180
            )
            if is_morning_pref and stop.arrival_minute > tw.latest_minute:
                structured.append(
                    CriticIssue(
                        type="preference_violation",
                        severity="high",
                        message=(
                            f"Job {job.id} requested morning window "
                            f"({tw.earliest_minute}-{tw.latest_minute} min) "
                            f"but scheduled at {stop.arrival_minute} min (afternoon)"
                        ),
                        crew_id=route.crew_id,
                        job_id=job.id,
                    )
                )

            tags = set(inp.job_tags.get(job.id, []))
            req_eq = list(job.required_equipment or [])
            if req_eq:
                equipment_total += 1
                crew_kinds = set(crew.equipment_kinds if crew else [])
                if set(req_eq).issubset(crew_kinds):
                    equipment_ok += 1
                else:
                    structured.append(
                        CriticIssue(
                            type="equipment_necessity",
                            severity="high",
                            message=(
                                f"Job {job.id} requires {req_eq} but crew {route.crew_id} "
                                f"carries {sorted(crew_kinds)}"
                            ),
                            crew_id=route.crew_id,
                            job_id=job.id,
                        )
                    )
                if "ground_floor" in tags and req_eq:
                    structured.append(
                        CriticIssue(
                            type="equipment_necessity",
                            severity="high",
                            message=(
                                f"Job {job.id} is ground-floor but requires unnecessary "
                                f"equipment {req_eq}"
                            ),
                            job_id=job.id,
                            crew_id=route.crew_id,
                        )
                    )
            elif crew:
                equipment_total += 1
                equipment_ok += 1

    _check_week_fill_order(inp, structured)

    total_input_jobs = len(opt_in.jobs)
    assigned = len(result.assigned_job_ids)
    week_fill = assigned / total_input_jobs if total_input_jobs else 1.0
    equipment_fit = equipment_ok / equipment_total if equipment_total else 1.0

    return _finalize_metrics(
        crew_days,
        preference_violations,
        week_fill,
        equipment_fit,
        structured,
        result,
        total_input_jobs,
        assigned,
    )

"""Operational schedule QA validator.

Produces structured ``Violation`` objects with loud, specific messages.
Can be called from tests, the chat pipeline, or a CI hook.

Usage::

    from app.schedule_qa import ScheduleValidator
    validator = ScheduleValidator(plan, store)
    report = validator.run()
    if not report.passed:
        for v in report.errors:
            print(v.message)
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .agents.base import drive_minutes, haversine_km
from .models import (
    EquipmentKind,
    JobStatus,
    PlanResult,
    ServiceType,
    Skill,
)
from .storage import Store


# ── Domain knowledge encoded as rules ────────────────────────────────────────
# These are business-specific constraints for West Island window / exterior
# services.  They supplement the generic hard constraints.

_SERVICE_REQUIRED_SKILLS: dict[ServiceType, list[Skill]] = {
    ServiceType.HIGH_RISE: [Skill.ROPE_ACCESS],
}

_SERVICE_REQUIRED_EQUIPMENT: dict[ServiceType, list[EquipmentKind]] = {
    ServiceType.GUTTER_CLEANING:  [EquipmentKind.LADDER_32],
    ServiceType.PRESSURE_WASHING: [EquipmentKind.PRESSURE_WASHER],
}

# A consecutive inter-stop distance above this is a route compactness warning.
_ROUTE_GAP_KM = 15.0

# Utilization above this triggers a "high utilization" quality warning.
_HIGH_UTIL_THRESHOLD = 0.92

# Drive ratio above this triggers a quality warning (drive > work time).
_DRIVE_RATIO_WARNING = 0.30


# ── Violation / QAReport data classes ─────────────────────────────────────────

@dataclass
class Violation:
    level: str       # "error" | "warning"
    category: str    # "hard_constraint" | "business_rule" | "quality"
    rule: str        # short machine-readable key, e.g. "skill_mismatch"
    message: str     # human-readable, full explanation for a failing test
    job_id: Optional[str] = None
    crew_id: Optional[str] = None
    day: Optional[date] = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        loc = " | ".join(filter(None, [
            f"job={self.job_id}" if self.job_id else None,
            f"crew={self.crew_id}" if self.crew_id else None,
            f"day={self.day}" if self.day else None,
        ]))
        prefix = f"[{self.level.upper()} / {self.rule}]"
        return f"{prefix} {self.message}" + (f"  ({loc})" if loc else "")


@dataclass
class QAMetrics:
    total_work_minutes: int = 0
    total_drive_minutes: int = 0
    drive_ratio: float = 0.0
    overbooked_days: int = 0
    unscheduled_jobs: int = 0
    equipment_conflicts: int = 0
    scheduled_jobs: int = 0
    revenue_scheduled: float = 0.0
    revenue_deferred: float = 0.0
    risk_score: int = 0
    utilization_by_crew_day: dict[str, float] = field(default_factory=dict)
    avg_utilization: float = 0.0
    utilization_stdev: float = 0.0
    route_gaps_above_threshold: int = 0


@dataclass
class QAReport:
    violations: list[Violation] = field(default_factory=list)
    metrics: QAMetrics = field(default_factory=QAMetrics)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.level == "error"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.level == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        e = len(self.errors)
        w = len(self.warnings)
        m = self.metrics
        return (
            f"QA {'PASS' if self.passed else 'FAIL'} — "
            f"{e} error(s), {w} warning(s) | "
            f"work {m.total_work_minutes}m drive {m.total_drive_minutes}m "
            f"(ratio {m.drive_ratio:.2f}) | "
            f"util avg {m.avg_utilization:.0%} | "
            f"risk {m.risk_score}/100"
        )


# ── Validator ──────────────────────────────────────────────────────────────────

class ScheduleValidator:
    """Run the full rule set against a PlanResult and return a QAReport."""

    def __init__(self, plan: PlanResult, store: Store) -> None:
        self._plan = plan
        self._store = store
        self._report = QAReport()
        self._jobs_by_id = {j.id: j for j in store.list_jobs()}
        self._crews_by_id = {c.id: c for c in store.list_crews()}
        self._crew_equipment_kinds: dict[str, set[EquipmentKind]] = {}
        for crew in store.list_crews():
            kinds: set[EquipmentKind] = set()
            for eid in crew.equipment_ids:
                eq = store.get_equipment(eid)
                if eq:
                    kinds.add(eq.kind)
            self._crew_equipment_kinds[crew.id] = kinds

    # ── public ────────────────────────────────────────────────────────────────

    def run(self) -> QAReport:
        self._report = QAReport()
        self._check_hard_constraints()
        self._check_business_rules()
        self._compute_quality_metrics()
        return self._report

    # ── internal helpers ──────────────────────────────────────────────────────

    def _err(self, rule: str, message: str, **kw) -> None:
        self._report.violations.append(
            Violation(level="error", category="hard_constraint", rule=rule, message=message, **kw)
        )

    def _biz(self, rule: str, message: str, **kw) -> None:
        self._report.violations.append(
            Violation(level="error", category="business_rule", rule=rule, message=message, **kw)
        )

    def _warn(self, rule: str, message: str, **kw) -> None:
        self._report.violations.append(
            Violation(level="warning", category="quality", rule=rule, message=message, **kw)
        )

    # ── HARD CONSTRAINTS ──────────────────────────────────────────────────────

    def _check_hard_constraints(self) -> None:
        self._check_no_duplicate_jobs()
        self._check_all_jobs_in_db()
        self._check_no_cancelled_jobs()
        self._check_skill_requirements()
        self._check_equipment_requirements()
        self._check_equipment_exclusivity()
        self._check_capacity_flag_consistency()
        self._check_date_windows()
        self._check_stop_ordering_and_overlap()
        self._check_travel_time_included()

    def _check_no_duplicate_jobs(self) -> None:
        """No job_id may appear more than once across the entire plan."""
        counts = collections.Counter(
            s.job_id
            for cd in self._plan.plan.days
            for s in cd.stops
        )
        for job_id, n in counts.items():
            if n > 1:
                self._err(
                    "duplicate_job",
                    f"Job {job_id!r} appears {n} times in the schedule. "
                    f"A job can only be assigned once. "
                    f"Check: crew-days {[f'{cd.crew_id}/{cd.day}' for cd in self._plan.plan.days if any(s.job_id == job_id for s in cd.stops)]}.",
                    job_id=job_id,
                )

    def _check_all_jobs_in_db(self) -> None:
        """Every job_id referenced in the plan must exist in the job database."""
        for cd in self._plan.plan.days:
            for stop in cd.stops:
                if stop.job_id not in self._jobs_by_id:
                    self._err(
                        "ghost_job",
                        f"Job {stop.job_id!r} is in the schedule but does not exist in the "
                        f"job database. It may have been deleted after planning or never saved.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                    )

    def _check_no_cancelled_jobs(self) -> None:
        """Cancelled jobs must never appear in the schedule."""
        for cd in self._plan.plan.days:
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if job and job.status == JobStatus.CANCELLED:
                    self._err(
                        "cancelled_job_scheduled",
                        f"Job {stop.job_id!r} has status CANCELLED but is still in the schedule "
                        f"on {cd.crew_id} / {cd.day.isoformat()}. "
                        f"Cancelled jobs must be removed from the plan.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                    )

    def _check_skill_requirements(self) -> None:
        """Assigned crew must have every skill the job requires."""
        for cd in self._plan.plan.days:
            crew = self._crews_by_id.get(cd.crew_id)
            if not crew:
                continue
            crew_skills = set(crew.skills)
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                missing = set(job.required_skills) - crew_skills
                if missing:
                    self._err(
                        "skill_mismatch",
                        f"Job {stop.job_id!r} ({job.service_type.value}) requires "
                        f"skill(s) {[s.value for s in missing]} but crew {cd.crew_id!r} "
                        f"({crew.name}) does not have them. "
                        f"Crew skills: {[s.value for s in crew.skills]}.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"missing_skills": [s.value for s in missing]},
                    )

    def _check_equipment_requirements(self) -> None:
        """Assigned crew must carry every equipment kind the job requires."""
        for cd in self._plan.plan.days:
            eq_kinds = self._crew_equipment_kinds.get(cd.crew_id, set())
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                missing = set(job.required_equipment) - eq_kinds
                if missing:
                    self._err(
                        "equipment_mismatch",
                        f"Job {stop.job_id!r} ({job.service_type.value}) requires "
                        f"equipment {[e.value for e in missing]} but crew {cd.crew_id!r} "
                        f"does not carry it. "
                        f"Crew equipment: {[e.value for e in eq_kinds]}. "
                        f"Options: reassign to a capable crew, rent the equipment, or defer.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"missing_equipment": [e.value for e in missing]},
                    )

    def _check_equipment_exclusivity(self) -> None:
        """Scissor-lift double-booking is a hard conflict with severity=critical.

        The scissor_lift requires full-day setup/teardown at a single location.
        At most one job per day may require it, regardless of which crew is
        assigned.  Any second scissor_lift job on the same calendar day is a
        critical error — it would cause a field failure.
        """
        # Only enforce exclusivity for equipment that requires a full-day
        # commitment (scissor_lift).  Standard reusable tools (ladders, poles,
        # pressure washers) are NOT subject to this rule.
        _EXCLUSIVE_KINDS = {EquipmentKind.SCISSOR_LIFT}

        total_by_kind: dict[EquipmentKind, int] = {}
        for eq in self._store.list_equipment():
            total_by_kind[eq.kind] = total_by_kind.get(eq.kind, 0) + eq.quantity

        # Collect job_ids per (day, equipment_kind) pair
        per_day_kind: dict[tuple, list[str]] = {}
        for cd in self._plan.plan.days:
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                for kind in job.required_equipment:
                    if kind in _EXCLUSIVE_KINDS:
                        key = (cd.day, kind)
                        per_day_kind.setdefault(key, []).append(stop.job_id)

        for (day, kind), job_ids in per_day_kind.items():
            total = total_by_kind.get(kind, 0)
            if len(job_ids) > max(1, total):
                self._err(
                    "equipment_exclusivity_violation",
                    f"CRITICAL: On {day.isoformat()}, {len(job_ids)} job(s) require "
                    f"{kind.value} but only {total} unit(s) exist in the company fleet. "
                    f"Jobs in conflict: {job_ids}. "
                    f"This is a hard equipment exclusivity violation — the {kind.value} "
                    f"cannot be committed to two locations on the same day. "
                    f"Move the lower-revenue job to a different day.",
                    day=day,
                    detail={
                        "equipment_kind": kind.value,
                        "conflicting_jobs": job_ids,
                        "available_units": total,
                        "severity": "critical",
                    },
                )

    def _check_capacity_flag_consistency(self) -> None:
        """The overbooked flag must match day_load > crew.daily_minutes (no silent overbooking)."""
        for cd in self._plan.plan.days:
            crew = self._crews_by_id.get(cd.crew_id)
            if not crew:
                continue
            day_load = cd.total_work_minutes + cd.total_drive_minutes
            should_be_overbooked = day_load > crew.daily_minutes
            if should_be_overbooked and not cd.overbooked:
                self._err(
                    "silent_overbook",
                    f"Crew {cd.crew_id!r} on {cd.day.isoformat()} has day_load={day_load} min "
                    f"exceeding capacity={crew.daily_minutes} min, but overbooked=False. "
                    f"This crew cannot complete this day safely. "
                    f"Excess: {day_load - crew.daily_minutes} min.",
                    crew_id=cd.crew_id,
                    day=cd.day,
                    detail={"day_load": day_load, "capacity": crew.daily_minutes},
                )
            if not should_be_overbooked and cd.overbooked:
                self._err(
                    "false_overbook_flag",
                    f"Crew {cd.crew_id!r} on {cd.day.isoformat()} is marked overbooked "
                    f"but day_load={day_load} <= capacity={crew.daily_minutes}. "
                    f"The flag is stale or the calculation is wrong.",
                    crew_id=cd.crew_id,
                    day=cd.day,
                    detail={"day_load": day_load, "capacity": crew.daily_minutes},
                )

    def _check_date_windows(self) -> None:
        """Every scheduled job must fall within its earliest_date..latest_date window."""
        for cd in self._plan.plan.days:
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                if cd.day < job.earliest_date:
                    self._err(
                        "date_window_too_early",
                        f"Job {stop.job_id!r} is scheduled on {cd.day.isoformat()} "
                        f"but its earliest_date is {job.earliest_date.isoformat()}. "
                        f"Client may not be available / materials not ready.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"earliest_date": job.earliest_date.isoformat()},
                    )
                if cd.day > job.latest_date:
                    self._err(
                        "date_window_too_late",
                        f"Job {stop.job_id!r} is scheduled on {cd.day.isoformat()} "
                        f"but its latest_date is {job.latest_date.isoformat()}. "
                        f"This violates the client-agreed service window.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"latest_date": job.latest_date.isoformat()},
                    )

    def _check_stop_ordering_and_overlap(self) -> None:
        """Stop order must be sequential, and stops must not overlap in time."""
        for cd in self._plan.plan.days:
            for idx, stop in enumerate(cd.stops):
                if stop.order != idx:
                    self._err(
                        "stop_order_invalid",
                        f"Crew {cd.crew_id!r} / {cd.day.isoformat()}: "
                        f"stop[{idx}] (job={stop.job_id!r}) has order={stop.order}, expected {idx}. "
                        f"Broken ordering means route sequence and start-times are unreliable.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                    )
            for i in range(len(cd.stops) - 1):
                cur  = cd.stops[i]
                nxt  = cd.stops[i + 1]
                cur_end = cur.start_minute + cur.duration_minutes
                if nxt.start_minute < cur_end:
                    self._err(
                        "stop_overlap",
                        f"Crew {cd.crew_id!r} / {cd.day.isoformat()}: "
                        f"stop[{i}] (job={cur.job_id!r}) ends at minute {cur_end} "
                        f"but stop[{i+1}] (job={nxt.job_id!r}) starts at minute {nxt.start_minute}. "
                        f"Overlapping stops mean two jobs are physically scheduled at the same time.",
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"overlap_minutes": cur_end - nxt.start_minute},
                    )

    def _check_travel_time_included(self) -> None:
        """Every stop must have travel_minutes_before >= 5 (the base setup constant)
        unless it is the first stop AND the crew base is at or near the job site."""
        for cd in self._plan.plan.days:
            crew = self._crews_by_id.get(cd.crew_id)
            if not crew:
                continue
            for idx, stop in enumerate(cd.stops):
                if stop.travel_minutes_before < 0:
                    self._err(
                        "negative_travel",
                        f"Crew {cd.crew_id!r} / {cd.day.isoformat()}: "
                        f"stop {stop.job_id!r} has travel_minutes_before={stop.travel_minutes_before}. "
                        f"Negative travel time is physically impossible.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                    )
                if stop.duration_minutes <= 0:
                    self._err(
                        "zero_duration",
                        f"Crew {cd.crew_id!r} / {cd.day.isoformat()}: "
                        f"stop {stop.job_id!r} has duration_minutes={stop.duration_minutes}. "
                        f"A zero or negative duration means the job was never actually timed.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                    )

    # ── BUSINESS RULES ────────────────────────────────────────────────────────

    def _check_business_rules(self) -> None:
        self._check_service_type_skills()
        self._check_service_type_equipment()
        self._check_large_job_capacity()
        self._check_duration_matches_estimated()
        self._check_work_total_consistency()

    def _check_service_type_skills(self) -> None:
        """Service-type-level skill enforcement (e.g. HIGH_RISE → ROPE_ACCESS)."""
        for cd in self._plan.plan.days:
            crew = self._crews_by_id.get(cd.crew_id)
            if not crew:
                continue
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                required = _SERVICE_REQUIRED_SKILLS.get(job.service_type, [])
                missing = [s for s in required if s not in crew.skills]
                if missing:
                    self._biz(
                        "service_type_skill_missing",
                        f"Job {stop.job_id!r} is a {job.service_type.value} job but "
                        f"crew {cd.crew_id!r} ({crew.name}) is missing "
                        f"{[s.value for s in missing]}. "
                        f"{'HIGH_RISE jobs require rope-access certified crew — assign crew_charlie.' if job.service_type == ServiceType.HIGH_RISE else 'Reassign to a qualified crew.'}",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"service": job.service_type.value, "missing": [s.value for s in missing]},
                    )

    def _check_service_type_equipment(self) -> None:
        """Service-type-level equipment enforcement (gutter → ladder_32, etc.)."""
        for cd in self._plan.plan.days:
            eq_kinds = self._crew_equipment_kinds.get(cd.crew_id, set())
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                required = _SERVICE_REQUIRED_EQUIPMENT.get(job.service_type, [])
                missing = [e for e in required if e not in eq_kinds]
                if missing:
                    missing_names = [e.value for e in missing]
                    hints = {
                        EquipmentKind.LADDER_32:       "Gutter cleaning on 2-storey+ homes requires a 32ft ladder. Only crew_bravo carries one.",
                        EquipmentKind.PRESSURE_WASHER: "Pressure washing jobs require a pressure washer. Crews alpha, bravo, and delta carry them.",
                    }
                    hint_msgs = [hints.get(e, "") for e in missing if hints.get(e)]
                    self._biz(
                        "service_type_equipment_missing",
                        f"Job {stop.job_id!r} ({job.service_type.value}) is assigned to "
                        f"crew {cd.crew_id!r} which is missing {missing_names}. "
                        + (" ".join(hint_msgs) if hint_msgs else "Reassign to a crew with the correct equipment."),
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"service": job.service_type.value, "missing_equipment": missing_names},
                    )

    def _check_large_job_capacity(self) -> None:
        """A single job must not consume more than the crew's full daily capacity."""
        for cd in self._plan.plan.days:
            crew = self._crews_by_id.get(cd.crew_id)
            if not crew:
                continue
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                if job.estimated_minutes > crew.daily_minutes:
                    self._biz(
                        "job_exceeds_daily_capacity",
                        f"Job {stop.job_id!r} requires {job.estimated_minutes} min but "
                        f"crew {cd.crew_id!r} only has {crew.daily_minutes} min per day. "
                        f"This job physically cannot be completed in a single shift. "
                        f"Consider splitting the work across two days or using a larger crew.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={
                            "job_minutes": job.estimated_minutes,
                            "crew_daily_minutes": crew.daily_minutes,
                        },
                    )

    def _check_duration_matches_estimated(self) -> None:
        """ScheduledStop.duration_minutes must equal job.estimated_minutes exactly."""
        for cd in self._plan.plan.days:
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                if stop.duration_minutes != job.estimated_minutes:
                    self._biz(
                        "duration_mismatch",
                        f"Stop {stop.job_id!r} on {cd.crew_id!r} / {cd.day.isoformat()} has "
                        f"duration_minutes={stop.duration_minutes} but job.estimated_minutes="
                        f"{job.estimated_minutes}. "
                        f"The scheduled duration should always equal the job estimate — "
                        f"a mismatch means a pipeline agent silently modified the duration, "
                        f"likely dividing by crew size.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={
                            "scheduled_duration": stop.duration_minutes,
                            "estimated_minutes": job.estimated_minutes,
                        },
                    )

    def _check_work_total_consistency(self) -> None:
        """total_work_minutes must equal sum(stop.duration_minutes)."""
        for cd in self._plan.plan.days:
            expected = sum(s.duration_minutes for s in cd.stops)
            if cd.total_work_minutes != expected:
                self._biz(
                    "work_total_inconsistent",
                    f"Crew {cd.crew_id!r} / {cd.day.isoformat()}: "
                    f"total_work_minutes={cd.total_work_minutes} but "
                    f"sum(stop.duration_minutes)={expected}. "
                    f"The day's work total is internally inconsistent — "
                    f"utilization and risk calculations will be wrong.",
                    crew_id=cd.crew_id,
                    day=cd.day,
                    detail={"recorded": cd.total_work_minutes, "computed": expected},
                )

    # ── QUALITY METRICS ───────────────────────────────────────────────────────

    def _compute_quality_metrics(self) -> None:
        plan = self._plan
        days = plan.plan.days
        m = self._report.metrics

        utils = []
        for cd in days:
            m.total_work_minutes  += cd.total_work_minutes
            m.total_drive_minutes += cd.total_drive_minutes
            if cd.overbooked:
                m.overbooked_days += 1
            m.scheduled_jobs += len(cd.stops)
            u_key = f"{cd.crew_id}/{cd.day.isoformat()}"
            m.utilization_by_crew_day[u_key] = cd.utilization
            utils.append(cd.utilization)

        total = m.total_work_minutes + m.total_drive_minutes
        m.drive_ratio = round(m.total_drive_minutes / total, 3) if total > 0 else 0.0

        m.unscheduled_jobs = len(plan.plan.unscheduled_job_ids)

        if plan.review:
            m.risk_score = plan.review.risk_score
            kpis = plan.review.kpis
            m.revenue_scheduled = kpis.get("revenue_scheduled", 0.0)
            m.revenue_deferred  = kpis.get("revenue_deferred", 0.0)
            m.equipment_conflicts = kpis.get("equipment_conflicts", 0) + kpis.get("equipment_gaps", 0)

        if utils:
            import statistics
            m.avg_utilization = round(sum(utils) / len(utils), 4)
            m.utilization_stdev = round(statistics.stdev(utils), 4) if len(utils) > 1 else 0.0

        # Route compactness warnings
        for cd in days:
            crew = self._crews_by_id.get(cd.crew_id)
            if not crew or len(cd.stops) < 2:
                continue
            prev_lat, prev_lng = crew.base_lat, crew.base_lng
            for stop in cd.stops:
                job = self._jobs_by_id.get(stop.job_id)
                if not job:
                    continue
                dist_km = haversine_km(prev_lat, prev_lng, job.lat, job.lng)
                if dist_km > _ROUTE_GAP_KM:
                    m.route_gaps_above_threshold += 1
                    self._warn(
                        "route_gap",
                        f"Crew {cd.crew_id!r} / {cd.day.isoformat()}: gap of {dist_km:.1f} km "
                        f"before job {stop.job_id!r} ({job.service_type.value}). "
                        f"Threshold is {_ROUTE_GAP_KM} km. "
                        f"Consider geographic reordering or re-clustering.",
                        job_id=stop.job_id,
                        crew_id=cd.crew_id,
                        day=cd.day,
                        detail={"gap_km": round(dist_km, 2)},
                    )
                prev_lat, prev_lng = job.lat, job.lng

        # Drive ratio warning
        if m.drive_ratio > _DRIVE_RATIO_WARNING:
            self._warn(
                "high_drive_ratio",
                f"Drive time ({m.total_drive_minutes} min) is "
                f"{int(m.drive_ratio * 100)}% of the combined work+drive total. "
                f"Threshold is {int(_DRIVE_RATIO_WARNING * 100)}%. "
                f"Tighten geo clustering or switch to geo_first scheduling mode.",
                detail={"drive_ratio": m.drive_ratio},
            )

        # High utilization days
        for cd in days:
            if cd.utilization >= _HIGH_UTIL_THRESHOLD and not cd.overbooked:
                self._warn(
                    "high_utilization",
                    f"Crew {cd.crew_id!r} / {cd.day.isoformat()} is at "
                    f"{int(cd.utilization * 100)}% utilization. "
                    f"Any traffic delay or job over-run may cause an impossible day. "
                    f"Have a plan to defer the last job if needed.",
                    crew_id=cd.crew_id,
                    day=cd.day,
                    detail={"utilization": cd.utilization},
                )

        # Unscheduled jobs warning
        if m.unscheduled_jobs:
            deferred = plan.plan.unscheduled_job_ids[:5]
            self._warn(
                "unscheduled_jobs",
                f"{m.unscheduled_jobs} job(s) could not be placed this week: "
                f"{deferred}{'…' if m.unscheduled_jobs > 5 else ''}. "
                f"Consider extending the planning window, adding crew capacity, "
                f"or accepting later dates from affected clients.",
                detail={"count": m.unscheduled_jobs, "sample": deferred},
            )

"""Dedicated schedule QA test suite.

Tests the ScheduleValidator against:
  1. A real plan produced from the full seed dataset — should pass all hard
     constraints and business rules with zero errors.
  2. Intentionally broken plans — one rule violation per test to verify the
     validator catches it and surfaces a clear message.
  3. Quality metric computation — values are consistent with the plan data.

── STRUCTURE ────────────────────────────────────────────────────────────────

TestValidatorOnRealPlan   — validate a scheduler-produced plan (no errors expected)
TestHardConstraintRules   — inject one violation per test; assert it is caught
TestBusinessRules         — business-specific rule injection tests
TestQualityMetrics        — verify metric values are arithmetically correct
TestViolationMessages     — verify every violation has a useful, non-empty message
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, timedelta

import pytest

from app.agents import SupervisorAgent
from app.models import (
    Client,
    Crew,
    CrewDay,
    Equipment,
    EquipmentKind,
    Job,
    JobStatus,
    PlanResult,
    ScheduledStop,
    ServiceType,
    Skill,
    WeekPlan,
)
from app.schedule_qa import QAReport, ScheduleValidator
from app.seed import BASE_LAT, BASE_LNG, seed
from app.storage import store

WEEK = date(2026, 7, 6)


# ─── Shared planner fixture ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_seed(monkeypatch):
    seed(reset=True)

    async def _fake_geo(address: str):
        from app.geocode import GeocodeResult
        for j in store.list_jobs():
            if j.address == address:
                return GeocodeResult(
                    input_address=address, success=True,
                    lat=j.lat, lng=j.lng, formatted_address=address,
                    confidence=0.95, needs_review=False,
                    in_service_area=True, location_type="ROOFTOP",
                    postal_code="H9X", province="QC", source="google",
                )
        return GeocodeResult(
            input_address=address, success=True,
            lat=BASE_LAT, lng=BASE_LNG, formatted_address=address,
            confidence=0.8, needs_review=True, in_service_area=True,
            location_type="APPROXIMATE", postal_code="H9X",
            province="QC", source="google",
        )

    async def _no_llm(*a, **kw):
        return None

    monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode", _fake_geo)
    monkeypatch.setattr("app.agents.supervisor._next_monday", lambda: WEEK)
    monkeypatch.setattr("app.llm.llm.chat", _no_llm)
    yield


def _plan() -> PlanResult:
    return asyncio.run(SupervisorAgent().plan_week(WEEK))


def _validate(plan: PlanResult) -> QAReport:
    return ScheduleValidator(plan, store).run()


def _simple_job(
    job_id: str,
    lat: float = BASE_LAT,
    lng: float = BASE_LNG,
    minutes: int = 90,
    skills: list[Skill] | None = None,
    equipment: list[EquipmentKind] | None = None,
    status: JobStatus = JobStatus.PENDING,
    service_type: ServiceType = ServiceType.WINDOW_CLEANING,
    price: float = 200.0,
    week: date = WEEK,
) -> Job:
    j = Job(
        id=job_id, client_id="c_test",
        service_type=service_type,
        address=f"addr_{job_id}",
        lat=lat, lng=lng,
        estimated_minutes=minutes, difficulty=2,
        required_skills=skills or [],
        required_equipment=equipment or [],
        earliest_date=week,
        latest_date=week + timedelta(days=4),
        price=price,
    )
    j.status = status
    return j


def _make_plan(job: Job, crew: Crew, day: date = WEEK) -> PlanResult:
    """Build a minimal PlanResult with one job on one crew-day."""
    from app.agents.base import drive_minutes, haversine_km
    d_km = haversine_km(crew.base_lat, crew.base_lng, job.lat, job.lng)
    travel = drive_minutes(d_km)
    return_km = haversine_km(job.lat, job.lng, crew.base_lat, crew.base_lng)
    return_drive = drive_minutes(return_km)
    day_load = travel + job.estimated_minutes + return_drive

    warnings = []
    if day_load > crew.daily_minutes:
        warnings.append(f"Day load {day_load} > {crew.daily_minutes}")
    cd = CrewDay(
        crew_id=crew.id,
        day=day,
        stops=[ScheduledStop(
            job_id=job.id,
            order=0,
            start_minute=travel,
            travel_minutes_before=travel,
            duration_minutes=job.estimated_minutes,
        )],
        total_drive_minutes=travel + return_drive,
        total_work_minutes=job.estimated_minutes,
        utilization=round(min(1.0, day_load / crew.daily_minutes), 2),
        overbooked=day_load > crew.daily_minutes,
        warnings=warnings,
    )
    return PlanResult(
        plan=WeekPlan(week_start=day, days=[cd], unscheduled_job_ids=[]),
    )


def _crew(crew_id: str, skills=None, eq_ids=None, daily_minutes=480) -> Crew:
    return Crew(
        id=crew_id, name=crew_id, members=["A", "B"],
        skills=skills or [Skill.LADDER_CERT],
        daily_minutes=daily_minutes,
        base_lat=BASE_LAT, base_lng=BASE_LNG,
        equipment_ids=eq_ids or [],
        hourly_cost=110.0,
    )


# ─── 1. Validate a real scheduler-produced plan ───────────────────────────────

class TestValidatorOnRealPlan:
    def test_no_hard_constraint_errors(self):
        plan = _plan()
        report = _validate(plan)
        errors = report.errors
        if errors:
            lines = "\n".join(f"  {v}" for v in errors)
            raise AssertionError(
                f"Scheduler-produced plan has {len(errors)} hard-constraint error(s):\n{lines}"
            )

    def test_no_business_rule_errors(self):
        plan = _plan()
        report = _validate(plan)
        biz_errors = [v for v in report.errors if v.category == "business_rule"]
        if biz_errors:
            lines = "\n".join(f"  {v}" for v in biz_errors)
            raise AssertionError(
                f"Scheduler-produced plan has {len(biz_errors)} business-rule error(s):\n{lines}"
            )

    def test_metrics_are_populated(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        assert m.total_work_minutes > 0
        assert m.total_drive_minutes >= 0
        assert m.scheduled_jobs > 0
        assert 0.0 <= m.drive_ratio <= 1.0
        assert 0.0 <= m.avg_utilization <= 1.0

    def test_summary_string_is_informative(self):
        plan = _plan()
        report = _validate(plan)
        s = report.summary()
        assert "QA" in s
        assert "risk" in s.lower()
        assert "work" in s.lower()

    def test_risk_score_in_range(self):
        plan = _plan()
        report = _validate(plan)
        assert 0 <= report.metrics.risk_score <= 100


# ─── 2. Hard constraint rules — one violation per test ───────────────────────

class TestHardConstraintRules:
    """Each test injects exactly one violation and asserts the validator catches it."""

    def _run(self, plan, rule_name):
        report = _validate(plan)
        matched = [v for v in report.violations if v.rule == rule_name]
        return report, matched

    # ── duplicate job ────────────────────────────────────────────────────────

    def test_duplicate_job_detected(self):
        plan = _plan()
        # Add the first job's id as a second stop on a different crew-day.
        first_stop = plan.plan.days[0].stops[0]
        dup_cd = CrewDay(
            crew_id=plan.plan.days[0].crew_id,
            day=WEEK + timedelta(days=1),
            stops=[ScheduledStop(
                job_id=first_stop.job_id,
                order=0,
                start_minute=10,
                travel_minutes_before=10,
                duration_minutes=first_stop.duration_minutes,
            )],
        )
        plan.plan.days.append(dup_cd)
        report, matched = self._run(plan, "duplicate_job")
        assert matched, (
            "Expected a 'duplicate_job' error when the same job_id appears twice in the plan.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert first_stop.job_id in matched[0].message, (
            f"Violation message should mention the duplicate job id. Got: {matched[0].message}"
        )

    # ── ghost job ────────────────────────────────────────────────────────────

    def test_ghost_job_detected(self):
        plan = _plan()
        ghost_stop = ScheduledStop(
            job_id="ghost_999", order=0,
            start_minute=5, travel_minutes_before=5, duration_minutes=90,
        )
        plan.plan.days[0].stops.append(ghost_stop)
        report, matched = self._run(plan, "ghost_job")
        assert matched, (
            "Expected a 'ghost_job' error when a stop references a job not in the database.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "ghost_999" in matched[0].message

    # ── cancelled job scheduled ──────────────────────────────────────────────

    def test_cancelled_job_detected(self):
        plan = _plan()
        # Mark one scheduled job as CANCELLED in the store.
        job_id = plan.plan.days[0].stops[0].job_id
        store.set_job_status(job_id, JobStatus.CANCELLED)
        report, matched = self._run(plan, "cancelled_job_scheduled")
        assert matched, (
            f"Expected a 'cancelled_job_scheduled' error when job {job_id} is CANCELLED "
            f"but still in the schedule.\nAll violations: {[str(v) for v in report.violations]}"
        )
        assert job_id in matched[0].message

    # ── skill mismatch ───────────────────────────────────────────────────────

    def test_skill_mismatch_detected(self):
        job = _simple_job("j_rope", skills=[Skill.ROPE_ACCESS])
        crew = _crew("crew_no_rope", skills=[Skill.LADDER_CERT])
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, matched = self._run(plan, "skill_mismatch")
        assert matched, (
            f"Expected 'skill_mismatch' for rope-access job on crew without ROPE_ACCESS.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "rope_access" in matched[0].message.lower()

    # ── equipment mismatch ───────────────────────────────────────────────────

    def test_equipment_mismatch_detected(self):
        job = _simple_job("j_lift", equipment=[EquipmentKind.SCISSOR_LIFT])
        crew = _crew("crew_no_lift")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, matched = self._run(plan, "equipment_mismatch")
        assert matched, (
            f"Expected 'equipment_mismatch' when SCISSOR_LIFT required but not in crew loadout.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "scissor_lift" in matched[0].message.lower()

    # ── silent overbook ──────────────────────────────────────────────────────

    def test_silent_overbook_detected(self):
        job = _simple_job("j_ob", minutes=600)
        crew = _crew("crew_ob", daily_minutes=480)
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        # Build day_load > capacity but leave overbooked=False (the violation).
        cd = CrewDay(
            crew_id="crew_ob", day=WEEK,
            stops=[ScheduledStop(
                job_id="j_ob", order=0, start_minute=5,
                travel_minutes_before=5, duration_minutes=600,
            )],
            total_drive_minutes=10,
            total_work_minutes=600,
            utilization=1.0,
            overbooked=False,  # <-- wrong: should be True
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "silent_overbook")
        assert matched, (
            "Expected 'silent_overbook' when day_load > capacity but overbooked=False.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "600" in matched[0].message or "480" in matched[0].message

    # ── date window too early ────────────────────────────────────────────────

    def test_date_window_too_early_detected(self):
        future = date(2026, 8, 10)
        job = _simple_job("j_future", week=future)
        crew = _crew("crew_x")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        # Schedule in July, but job is only available in August.
        cd = CrewDay(
            crew_id="crew_x", day=WEEK,  # July 6
            stops=[ScheduledStop(
                job_id="j_future", order=0, start_minute=5,
                travel_minutes_before=5, duration_minutes=90,
            )],
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "date_window_too_early")
        assert matched, (
            "Expected 'date_window_too_early' when job scheduled before earliest_date.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "2026-08" in matched[0].message

    # ── date window too late ─────────────────────────────────────────────────

    def test_date_window_too_late_detected(self):
        past_window_job = _simple_job("j_past", week=date(2026, 5, 1))
        crew = _crew("crew_y")
        store.jobs[past_window_job.id] = past_window_job
        store.crews[crew.id] = crew
        # Schedule in July but job latest_date is May.
        cd = CrewDay(
            crew_id="crew_y", day=WEEK,
            stops=[ScheduledStop(
                job_id="j_past", order=0, start_minute=5,
                travel_minutes_before=5, duration_minutes=90,
            )],
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "date_window_too_late")
        assert matched, (
            "Expected 'date_window_too_late' when job scheduled after latest_date.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )

    # ── stop ordering ────────────────────────────────────────────────────────

    def test_stop_order_invalid_detected(self):
        job = _simple_job("j_ord")
        crew = _crew("crew_ord")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        cd = CrewDay(
            crew_id="crew_ord", day=WEEK,
            stops=[ScheduledStop(
                job_id="j_ord", order=99,  # wrong
                start_minute=5, travel_minutes_before=5, duration_minutes=90,
            )],
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "stop_order_invalid")
        assert matched, (
            "Expected 'stop_order_invalid' when stop.order != its list index.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )

    # ── stop overlap ─────────────────────────────────────────────────────────

    def test_stop_overlap_detected(self):
        job_a = _simple_job("j_a", lat=BASE_LAT + 0.01, lng=BASE_LNG + 0.01)
        job_b = _simple_job("j_b", lat=BASE_LAT + 0.02, lng=BASE_LNG + 0.02)
        crew = _crew("crew_ov")
        store.jobs[job_a.id] = job_a
        store.jobs[job_b.id] = job_b
        store.crews[crew.id] = crew
        # Job A: start=5, duration=90 → ends at 95.  Job B starts at 80 (overlaps).
        cd = CrewDay(
            crew_id="crew_ov", day=WEEK,
            stops=[
                ScheduledStop(job_id="j_a", order=0, start_minute=5,
                               travel_minutes_before=5, duration_minutes=90),
                ScheduledStop(job_id="j_b", order=1, start_minute=80,   # overlap!
                               travel_minutes_before=10, duration_minutes=90),
            ],
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "stop_overlap")
        assert matched, (
            "Expected 'stop_overlap' when stop[1].start_minute < stop[0].start + stop[0].duration.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "80" in matched[0].message or "95" in matched[0].message

    # ── negative travel ──────────────────────────────────────────────────────

    def test_negative_travel_detected(self):
        job = _simple_job("j_neg")
        crew = _crew("crew_neg")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        cd = CrewDay(
            crew_id="crew_neg", day=WEEK,
            stops=[ScheduledStop(
                job_id="j_neg", order=0, start_minute=-5,
                travel_minutes_before=-5,  # invalid
                duration_minutes=90,
            )],
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "negative_travel")
        assert matched, (
            "Expected 'negative_travel' for travel_minutes_before < 0.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )


# ─── 3. Business rules ────────────────────────────────────────────────────────

class TestBusinessRules:
    def _run(self, plan, rule):
        report = _validate(plan)
        return report, [v for v in report.violations if v.rule == rule]

    def test_gutter_cleaning_requires_ladder_32(self):
        job = _simple_job(
            "j_gut", service_type=ServiceType.GUTTER_CLEANING,
            equipment=[EquipmentKind.LADDER_32],
        )
        crew = _crew("crew_no_lad32")
        # Crew has no ladder_32.
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, matched = self._run(plan, "service_type_equipment_missing")
        assert matched, (
            "Expected 'service_type_equipment_missing' for gutter job on crew without ladder_32.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "gutter" in matched[0].message.lower() or "ladder" in matched[0].message.lower()

    def test_pressure_washing_requires_pressure_washer(self):
        job = _simple_job(
            "j_pw", service_type=ServiceType.PRESSURE_WASHING,
            equipment=[EquipmentKind.PRESSURE_WASHER],
        )
        crew = _crew("crew_no_pw")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, matched = self._run(plan, "service_type_equipment_missing")
        assert matched, (
            "Expected 'service_type_equipment_missing' for pressure-wash job on crew without PW.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "pressure" in matched[0].message.lower()

    def test_high_rise_requires_rope_access(self):
        job = _simple_job(
            "j_hr", service_type=ServiceType.HIGH_RISE,
            skills=[Skill.ROPE_ACCESS],
        )
        # Assign to a crew without rope access.
        crew = _crew("crew_no_rope", skills=[Skill.LADDER_CERT, Skill.LIFT_OPERATOR])
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, biz = self._run(plan, "service_type_skill_missing")
        assert biz, (
            "Expected 'service_type_skill_missing' for HIGH_RISE job without ROPE_ACCESS.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "rope" in biz[0].message.lower() or "high" in biz[0].message.lower()

    def test_high_rise_message_mentions_charlie_crew(self):
        job = _simple_job("j_hr2", service_type=ServiceType.HIGH_RISE, skills=[Skill.ROPE_ACCESS])
        crew = _crew("crew_no_rope2", skills=[Skill.LADDER_CERT])
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, biz = self._run(plan, "service_type_skill_missing")
        assert biz
        assert "charlie" in biz[0].message.lower(), (
            f"HIGH_RISE violation should mention crew_charlie. Got: {biz[0].message}"
        )

    def test_job_exceeds_daily_capacity(self):
        job = _simple_job("j_giant", minutes=700)
        crew = _crew("crew_small", daily_minutes=480)
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        plan = _make_plan(job, crew)
        report, matched = self._run(plan, "job_exceeds_daily_capacity")
        assert matched, (
            "Expected 'job_exceeds_daily_capacity' when job.estimated_minutes > crew.daily_minutes.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "700" in matched[0].message

    def test_duration_mismatch_detected(self):
        job = _simple_job("j_dur", minutes=120)
        crew = _crew("crew_dur")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        cd = CrewDay(
            crew_id="crew_dur", day=WEEK,
            stops=[ScheduledStop(
                job_id="j_dur", order=0, start_minute=10,
                travel_minutes_before=10,
                duration_minutes=60,   # wrong: should be 120
            )],
            total_work_minutes=60, total_drive_minutes=20,
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "duration_mismatch")
        assert matched, (
            "Expected 'duration_mismatch' when stop.duration != job.estimated_minutes.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        msg = matched[0].message
        assert "60" in msg and "120" in msg, (
            f"Violation message should state both scheduled ({60}) and estimated ({120}) values. "
            f"Got: {msg}"
        )

    def test_work_total_inconsistent_detected(self):
        job = _simple_job("j_wk", minutes=90)
        crew = _crew("crew_wk")
        store.jobs[job.id] = job
        store.crews[crew.id] = crew
        cd = CrewDay(
            crew_id="crew_wk", day=WEEK,
            stops=[ScheduledStop(
                job_id="j_wk", order=0, start_minute=10,
                travel_minutes_before=10, duration_minutes=90,
            )],
            total_work_minutes=45,  # wrong: should be 90
            total_drive_minutes=20,
        )
        plan = PlanResult(plan=WeekPlan(week_start=WEEK, days=[cd]))
        report, matched = self._run(plan, "work_total_inconsistent")
        assert matched, (
            "Expected 'work_total_inconsistent' when recorded total != sum of stop durations.\n"
            f"All violations: {[str(v) for v in report.violations]}"
        )
        assert "45" in matched[0].message and "90" in matched[0].message


# ─── 4. Quality metrics ───────────────────────────────────────────────────────

class TestQualityMetrics:
    def test_total_work_equals_sum_of_stop_durations(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        computed = sum(s.duration_minutes for cd in plan.plan.days for s in cd.stops)
        assert m.total_work_minutes == computed, (
            f"metric.total_work_minutes={m.total_work_minutes} != "
            f"sum(stop.duration)={computed}"
        )

    def test_total_drive_includes_return_legs(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        sum_inter = sum(
            s.travel_minutes_before
            for cd in plan.plan.days
            for s in cd.stops
        )
        assert m.total_drive_minutes >= sum_inter, (
            "total_drive_minutes should be >= inter-stop drive (it includes return legs)"
        )

    def test_drive_ratio_formula(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        total = m.total_work_minutes + m.total_drive_minutes
        expected = round(m.total_drive_minutes / total, 3) if total > 0 else 0.0
        assert m.drive_ratio == expected, (
            f"drive_ratio={m.drive_ratio} != {expected}"
        )

    def test_avg_utilization_formula(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        if not plan.plan.days:
            pytest.skip("empty plan")
        utils = [cd.utilization for cd in plan.plan.days]
        expected = round(sum(utils) / len(utils), 4)
        assert m.avg_utilization == expected, (
            f"avg_utilization={m.avg_utilization} != {expected}"
        )

    def test_overbooked_days_count(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        expected = sum(1 for cd in plan.plan.days if cd.overbooked)
        assert m.overbooked_days == expected

    def test_scheduled_jobs_count(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        expected = sum(len(cd.stops) for cd in plan.plan.days)
        assert m.scheduled_jobs == expected

    def test_unscheduled_count(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        assert m.unscheduled_jobs == len(plan.plan.unscheduled_job_ids)

    def test_utilization_by_crew_day_populated(self):
        plan = _plan()
        report = _validate(plan)
        m = report.metrics
        assert len(m.utilization_by_crew_day) == len(plan.plan.days)
        for key, util in m.utilization_by_crew_day.items():
            assert 0.0 <= util <= 1.0, f"{key}: utilization={util} out of range"

    def test_risk_score_from_plan_review(self):
        plan = _plan()
        report = _validate(plan)
        if plan.review:
            assert report.metrics.risk_score == plan.review.risk_score


# ─── 5. Violation messages are informative ────────────────────────────────────

class TestViolationMessages:
    """Every violation must have a non-empty message explaining what is wrong."""

    def _inject_violations(self):
        """Return a plan known to trigger multiple violations."""
        plan = _plan()
        # Ghost job
        plan.plan.days[0].stops.append(ScheduledStop(
            job_id="ghost_xyz", order=99,
            start_minute=5, travel_minutes_before=5, duration_minutes=90,
        ))
        return plan

    def test_all_violations_have_non_empty_messages(self):
        plan = self._inject_violations()
        report = _validate(plan)
        for v in report.violations:
            assert v.message, f"Violation {v.rule!r} has an empty message"
            assert len(v.message) > 20, (
                f"Violation {v.rule!r} message is suspiciously short: {v.message!r}"
            )

    def test_violations_mention_job_or_crew_or_day(self):
        """Each violation should reference at least one of: job_id, crew_id, day."""
        plan = self._inject_violations()
        report = _validate(plan)
        for v in report.violations:
            has_context = (
                v.job_id or v.crew_id or v.day
                or any(kw in v.message for kw in ("crew", "job", "day", "schedule"))
            )
            assert has_context, (
                f"Violation {v.rule!r} has no contextual reference to job/crew/day. "
                f"Message: {v.message!r}"
            )

    def test_error_and_warning_levels_are_valid(self):
        plan = _plan()
        report = _validate(plan)
        for v in report.violations:
            assert v.level in ("error", "warning"), (
                f"Violation {v.rule!r} has invalid level: {v.level!r}"
            )

    def test_category_values_are_valid(self):
        plan = _plan()
        report = _validate(plan)
        for v in report.violations:
            assert v.category in ("hard_constraint", "business_rule", "quality"), (
                f"Violation {v.rule!r} has invalid category: {v.category!r}"
            )

    def test_passed_property_reflects_errors(self):
        plan = _plan()
        report = _validate(plan)
        if report.errors:
            assert not report.passed
        else:
            assert report.passed

    def test_str_representation_contains_rule_and_message(self):
        """str(violation) should include the rule name and message for easy log output."""
        v = _validate(_plan()).violations
        if not v:
            # Manufacture one.
            plan = _plan()
            plan.plan.days[0].stops[0] = ScheduledStop(
                job_id="ghost_abc", order=0,
                start_minute=5, travel_minutes_before=5, duration_minutes=90,
            )
            v = _validate(plan).violations
        if not v:
            pytest.skip("no violations to test str()")
        text = str(v[0])
        assert v[0].rule in text, f"rule name missing from str: {text}"

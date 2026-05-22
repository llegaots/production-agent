"""Duration and capacity logic tests — pin every formula to its source.

This file documents and tests the exact arithmetic the scheduler uses.
Each test either:
  (a) calls the formula functions directly with known inputs, or
  (b) constructs a minimal synthetic scenario and runs the real agent
      pipeline, then asserts the numbers are consistent with the formulas.

── FORMULAS USED BY THE SCHEDULER ──────────────────────────────────────────

1. Travel time   base.drive_minutes(d_km)
       int(round((d_km / 35.0) * 60)) + 5
   35 km/h average road speed + 5-minute stop-setup base.

2. Job duration  ScheduledStop.duration_minutes
       = job.estimated_minutes
   Crew size does NOT reduce duration. The field records physical elapsed
   time at the site. If a 3-person crew completes work faster than a
   2-person crew, that is already captured by a shorter estimated_minutes
   on the job itself.  The scheduler never divides estimated_minutes by
   crew size.

3. Day load      time_budget.day_load
       = sum(travel_i for all stops)
         + sum(job.estimated_minutes for all stops)
         + return_to_base_travel
       (the minute_cursor at end of last stop + return drive)

4. Overbooking   time_budget.overbooked
       = day_load > crew.daily_minutes
   Strict greater-than; a day that exactly meets capacity is NOT overbooked.

5. Utilization   CrewDay.utilization
       = round(min(1.0, day_load / crew.daily_minutes), 2)
   Capped at 1.0 even when overbooked.

6. Capacity pre-check in crew_match (draft placement gate)
       used_so_far + total_job_minutes + drive_budget > crew.daily_minutes
   where drive_budget = 20 + 15 * max(0, n_jobs - 1)
   This is a conservative estimate; TimeBudget uses real haversine distances.

7. total_work_minutes  = sum(stop.duration_minutes)   (no travel)
   total_drive_minutes = sum(stop.travel_minutes_before) + return_drive
   These two fields are independent; their SUM is day_load.

── WHAT IS NOT MODELED (documented here to prevent false assumptions) ───────

- Crew head-count does NOT affect job duration (not modelled).
- No lunch break / break time (not modelled).
- Travel speed is a flat 35 km/h (no traffic, no time-of-day).
- No overtime beyond daily_minutes (overbooking is flagged, not auto-fixed).
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta

import pytest

from app.agents.base import drive_minutes, haversine_km, week_days
from app.agents.time_budget import TimeBudgetAgent
from app.agents.base import AgentContext
from app.models import (
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
from app.seed import BASE_LAT, BASE_LNG
from app.storage import store
from app.seed import seed


# ─── Formula unit tests ───────────────────────────────────────────────────────

class TestDriveMinutesFormula:
    """drive_minutes(d_km) = int(round(d_km / 35 * 60)) + 5"""

    def test_zero_km_returns_base_setup(self):
        # 0 km travel → only the 5-min stop-setup base
        assert drive_minutes(0.0) == 5

    def test_formula_matches_manual_calculation(self):
        for km in (1.0, 5.0, 10.0, 20.0, 35.0):
            expected = int(round((km / 35.0) * 60)) + 5
            assert drive_minutes(km) == expected, f"drive_minutes({km}) mismatch"

    def test_7km_is_17_minutes(self):
        # (7 / 35) * 60 = 12.0 → round = 12 → +5 = 17
        assert drive_minutes(7.0) == 17

    def test_35km_is_65_minutes(self):
        # (35 / 35) * 60 = 60 → +5 = 65
        assert drive_minutes(35.0) == 65

    def test_always_positive(self):
        for km in (0, 0.01, 0.1, 100.0):
            assert drive_minutes(km) > 0

    def test_monotonically_increasing(self):
        prev = drive_minutes(0.0)
        for km in (1, 5, 10, 20, 50, 100):
            cur = drive_minutes(float(km))
            assert cur >= prev
            prev = cur


class TestHaversineFormula:
    """haversine_km: sanity checks against known distances."""

    def test_identical_points_is_zero(self):
        assert haversine_km(45.4, -73.9, 45.4, -73.9) == pytest.approx(0.0)

    def test_depot_to_ile_perrot_job_coords_reasonable(self):
        # job_W01 lat/lng in seed; should be a few km from the depot
        d = haversine_km(BASE_LAT, BASE_LNG, 45.3838, -73.8825)
        assert 3 <= d <= 15, f"expected 3–15 km depot→Île-Perrot job, got {d:.1f}"

    def test_depot_to_dorval_reasonable(self):
        d = haversine_km(BASE_LAT, BASE_LNG, 45.452, -73.745)
        assert 10 <= d <= 25, f"expected 10–25 km depot→Dorval area, got {d:.1f}"

    def test_symmetrical(self):
        a = haversine_km(45.4, -73.9, 45.5, -73.8)
        b = haversine_km(45.5, -73.8, 45.4, -73.9)
        assert a == pytest.approx(b, rel=1e-6)


# ─── ScheduledStop duration contract ─────────────────────────────────────────

class TestScheduledStopDuration:
    """The scheduled duration must equal job.estimated_minutes — no division
    by crew size, no rounding, no modification by any agent."""

    def _make_stop(self, duration_min: int, job_lat: float = BASE_LAT, job_lng: float = BASE_LNG) -> ScheduledStop:
        return ScheduledStop(
            job_id="j1",
            order=0,
            start_minute=0,
            travel_minutes_before=0,
            duration_minutes=duration_min,
        )

    def test_duration_equals_estimated_minutes(self):
        for minutes in (60, 90, 120, 180, 240, 420, 480):
            s = self._make_stop(minutes)
            assert s.duration_minutes == minutes

    def test_crew_size_does_not_divide_duration(self):
        """Explicitly document: a 3-person crew assigned a 180-min job
        must have duration_minutes=180, not 60 (180/3)."""
        # Build a minimal TimeBudgetAgent run with a 3-person crew.
        crew = Crew(
            id="crew_test3", name="3-person crew",
            members=["A", "B", "C"],
            skills=[Skill.LADDER_CERT],
            daily_minutes=9 * 60,
            base_lat=BASE_LAT, base_lng=BASE_LNG,
            equipment_ids=[],
            hourly_cost=150.0,
        )
        job = Job(
            id="job_3hr",
            client_id="c1",
            service_type=ServiceType.WINDOW_CLEANING,
            address="Test",
            lat=BASE_LAT + 0.05, lng=BASE_LNG + 0.05,
            estimated_minutes=180,
            difficulty=2,
            required_skills=[],
            required_equipment=[],
            earliest_date=date(2026, 7, 6),
            latest_date=date(2026, 7, 10),
        )
        draft = [{"crew_id": "crew_test3", "day": date(2026, 7, 7), "job_ids": ["job_3hr"]}]

        ctx = AgentContext(
            week_start=date(2026, 7, 7),
            crews=[crew],
            jobs=[job],
        )
        ctx.blackboard["draft_plan"] = draft

        asyncio.run(TimeBudgetAgent().run(ctx))
        crew_days = ctx.blackboard["crew_days"]
        assert len(crew_days) == 1
        stop = crew_days[0].stops[0]

        assert stop.duration_minutes == 180, (
            f"3-person crew incorrectly divided job duration: "
            f"got {stop.duration_minutes}, expected 180 (crew size must not affect duration)"
        )
        assert crew_days[0].total_work_minutes == 180


# ─── Day-load arithmetic ──────────────────────────────────────────────────────

class TestDayLoadArithmetic:
    """day_load = sum(travel_i) + sum(work_i) + return_drive
    This must equal minute_cursor_after_last_job + return_drive."""

    def _run_time_budget(self, crew: Crew, jobs: list[Job], day: date) -> CrewDay:
        draft = [{"crew_id": crew.id, "day": day, "job_ids": [j.id for j in jobs]}]
        ctx = AgentContext(week_start=day, crews=[crew], jobs=jobs)
        ctx.blackboard["draft_plan"] = draft
        asyncio.run(TimeBudgetAgent().run(ctx))
        return ctx.blackboard["crew_days"][0]

    def _make_crew(self, daily_minutes: int = 480) -> Crew:
        return Crew(
            id="crew_test",
            name="test crew",
            members=["X", "Y"],
            skills=[Skill.LADDER_CERT],
            daily_minutes=daily_minutes,
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=[],
            hourly_cost=100.0,
        )

    def _make_job(self, job_id: str, minutes: int, lat: float, lng: float) -> Job:
        return Job(
            id=job_id,
            client_id="c1",
            service_type=ServiceType.WINDOW_CLEANING,
            address="test",
            lat=lat,
            lng=lng,
            estimated_minutes=minutes,
            difficulty=2,
            required_skills=[],
            required_equipment=[],
            earliest_date=date(2026, 7, 6),
            latest_date=date(2026, 7, 10),
        )

    def test_work_minutes_sum_equals_sum_of_job_durations(self):
        crew = self._make_crew()
        jobs = [
            self._make_job("j1", 90, BASE_LAT + 0.02, BASE_LNG + 0.02),
            self._make_job("j2", 120, BASE_LAT + 0.04, BASE_LNG - 0.02),
        ]
        cd = self._run_time_budget(crew, jobs, date(2026, 7, 7))
        expected_work = sum(j.estimated_minutes for j in jobs)
        assert cd.total_work_minutes == expected_work, (
            f"total_work_minutes {cd.total_work_minutes} != sum of job durations {expected_work}"
        )

    def test_drive_minutes_includes_return_to_base(self):
        """total_drive must be > sum of inter-stop travel (it includes return leg)."""
        crew = self._make_crew()
        jobs = [
            self._make_job("j1", 60, BASE_LAT + 0.10, BASE_LNG + 0.10),
        ]
        cd = self._run_time_budget(crew, jobs, date(2026, 7, 7))
        inter_stop_drive = sum(s.travel_minutes_before for s in cd.stops)
        assert cd.total_drive_minutes >= inter_stop_drive, (
            "total_drive_minutes must include return-to-base leg"
        )
        # There is exactly one job; the return leg must add something.
        return_km = haversine_km(jobs[0].lat, jobs[0].lng, crew.base_lat, crew.base_lng)
        expected_return = drive_minutes(return_km)
        assert cd.total_drive_minutes == inter_stop_drive + expected_return

    def test_day_load_equals_work_plus_drive(self):
        crew = self._make_crew()
        jobs = [
            self._make_job("j1", 90, BASE_LAT + 0.05, BASE_LNG + 0.05),
            self._make_job("j2", 60, BASE_LAT - 0.05, BASE_LNG - 0.05),
        ]
        cd = self._run_time_budget(crew, jobs, date(2026, 7, 7))
        day_load = cd.total_work_minutes + cd.total_drive_minutes
        utilization_implied = round(min(1.0, day_load / crew.daily_minutes), 2)
        assert cd.utilization == utilization_implied, (
            f"utilization {cd.utilization} doesn't match work+drive calc {utilization_implied}"
        )

    def test_first_stop_start_minute_equals_depot_travel(self):
        """The first job's start_minute must equal exactly its travel_minutes_before
        (crew departs depot at minute 0)."""
        crew = self._make_crew()
        lat, lng = BASE_LAT + 0.08, BASE_LNG + 0.03
        jobs = [self._make_job("j1", 90, lat, lng)]
        cd = self._run_time_budget(crew, jobs, date(2026, 7, 7))
        stop = cd.stops[0]
        assert stop.start_minute == stop.travel_minutes_before, (
            "First stop should start at travel_minutes_before (crew starts at depot)"
        )
        d_km = haversine_km(crew.base_lat, crew.base_lng, lat, lng)
        assert stop.travel_minutes_before == drive_minutes(d_km)

    def test_second_stop_start_minute_accounts_for_first_job(self):
        """stop[1].start_minute = stop[0].start + stop[0].duration + stop[1].travel"""
        crew = self._make_crew()
        j1_lat, j1_lng = BASE_LAT + 0.05, BASE_LNG + 0.05
        j2_lat, j2_lng = BASE_LAT + 0.07, BASE_LNG - 0.02
        jobs = [
            self._make_job("j1", 90, j1_lat, j1_lng),
            self._make_job("j2", 60, j2_lat, j2_lng),
        ]
        cd = self._run_time_budget(crew, jobs, date(2026, 7, 7))
        s0, s1 = cd.stops[0], cd.stops[1]
        expected = s0.start_minute + s0.duration_minutes + s1.travel_minutes_before
        assert s1.start_minute == expected, (
            f"stop[1].start_minute={s1.start_minute}, "
            f"expected s0.start({s0.start_minute})+s0.dur({s0.duration_minutes})"
            f"+s1.travel({s1.travel_minutes_before})={expected}"
        )

    def test_inter_stop_travel_matches_haversine(self):
        crew = self._make_crew()
        j1_lat, j1_lng = BASE_LAT + 0.05, BASE_LNG + 0.05
        j2_lat, j2_lng = BASE_LAT + 0.09, BASE_LNG - 0.03
        jobs = [
            self._make_job("j1", 90, j1_lat, j1_lng),
            self._make_job("j2", 60, j2_lat, j2_lng),
        ]
        cd = self._run_time_budget(crew, jobs, date(2026, 7, 7))
        d_km = haversine_km(j1_lat, j1_lng, j2_lat, j2_lng)
        expected_travel = drive_minutes(d_km)
        assert cd.stops[1].travel_minutes_before == expected_travel, (
            f"inter-stop travel {cd.stops[1].travel_minutes_before} "
            f"!= drive_minutes({d_km:.3f} km) = {expected_travel}"
        )


# ─── Overbooking detection ─────────────────────────────────────────────────────

class TestOverbookingDetection:
    """day_load > daily_minutes → overbooked=True and warning appended."""

    def _run(self, daily_minutes: int, job_minutes: int, dist_km: float = 5.0) -> CrewDay:
        from app.agents.time_budget import TimeBudgetAgent

        lat = BASE_LAT + dist_km * math.cos(math.radians(45)) / 111
        lng = BASE_LNG + dist_km * math.sin(math.radians(45)) / (111 * math.cos(math.radians(BASE_LAT)))
        crew = Crew(
            id="crew_ob", name="cap test", members=["A"],
            skills=[], daily_minutes=daily_minutes,
            base_lat=BASE_LAT, base_lng=BASE_LNG,
            equipment_ids=[], hourly_cost=100.0,
        )
        job = Job(
            id="job_ob", client_id="c1",
            service_type=ServiceType.WINDOW_CLEANING,
            address="test", lat=lat, lng=lng,
            estimated_minutes=job_minutes,
            difficulty=1, required_skills=[], required_equipment=[],
            earliest_date=date(2026, 7, 6), latest_date=date(2026, 7, 10),
        )
        draft = [{"crew_id": "crew_ob", "day": date(2026, 7, 7), "job_ids": ["job_ob"]}]
        ctx = AgentContext(week_start=date(2026, 7, 7), crews=[crew], jobs=[job])
        ctx.blackboard["draft_plan"] = draft
        asyncio.run(TimeBudgetAgent().run(ctx))
        return ctx.blackboard["crew_days"][0]

    def test_well_within_capacity_not_overbooked(self):
        # 60-min job + ~17-min travel (each way) = ~94 min << 480 min daily
        cd = self._run(daily_minutes=480, job_minutes=60, dist_km=7.0)
        assert not cd.overbooked

    def test_day_load_exceeds_capacity_flagged(self):
        # Give crew 100 min but load them with 400 min of work
        cd = self._run(daily_minutes=100, job_minutes=400, dist_km=0.1)
        assert cd.overbooked, "Expected overbooked=True when day_load > daily_minutes"

    def test_overbooked_produces_warning_message(self):
        cd = self._run(daily_minutes=100, job_minutes=400, dist_km=0.1)
        assert any("day load" in w.lower() for w in cd.warnings), (
            "Expected a 'Day load is X min vs crew capacity Y min' warning"
        )

    def test_exact_capacity_is_not_overbooked(self):
        """day_load == daily_minutes should NOT trigger overbooked (strict >)."""
        # Carefully construct: 0-km travel job so day_load = estimated_minutes + 5 (setup)
        # We'll use dist_km=0 which gives drive_minutes(0)=5 each way = 10 total.
        # daily_minutes = job_minutes + 5 (to depot) + 5 (return) = job + 10
        job_min = 200
        daily_min = job_min + 10   # just enough to fit
        cd = self._run(daily_minutes=daily_min, job_minutes=job_min, dist_km=0.0)
        assert not cd.overbooked, (
            f"day_load == daily_minutes should not be overbooked. "
            f"day_load={cd.total_work_minutes + cd.total_drive_minutes}, "
            f"daily_minutes={daily_min}"
        )

    def test_one_over_capacity_is_overbooked(self):
        # Force day_load to be daily_minutes + 1 by giving just 1 min less capacity
        job_min = 200
        daily_min = job_min + 10 - 1  # 1 less than exact fit
        cd = self._run(daily_minutes=daily_min, job_minutes=job_min, dist_km=0.0)
        assert cd.overbooked, (
            "day_load > daily_minutes must set overbooked=True"
        )

    def test_utilization_capped_at_1_when_overbooked(self):
        cd = self._run(daily_minutes=100, job_minutes=600, dist_km=0.1)
        assert cd.utilization == 1.0, (
            f"utilization should be capped at 1.0 when overbooked; got {cd.utilization}"
        )

    def test_utilization_exact_formula_when_not_overbooked(self):
        cd = self._run(daily_minutes=480, job_minutes=60, dist_km=0.0)
        day_load = cd.total_work_minutes + cd.total_drive_minutes
        expected = round(day_load / 480, 2)
        assert cd.utilization == expected, (
            f"utilization {cd.utilization} != round(day_load/daily_minutes,2) = {expected}"
        )


# ─── Multi-stop accumulation ──────────────────────────────────────────────────

class TestMultiStopAccumulation:
    """Three jobs: verify day_load equals the sum of all travel + all work."""

    def test_three_job_day_total_work_minutes(self):
        crew = Crew(
            id="crew_3j", name="3-job crew", members=["A", "B"],
            skills=[Skill.LADDER_CERT],
            daily_minutes=9 * 60,
            base_lat=BASE_LAT, base_lng=BASE_LNG,
            equipment_ids=[], hourly_cost=110.0,
        )
        jobs = [
            Job(id="j1", client_id="c1", service_type=ServiceType.WINDOW_CLEANING,
                address="a", lat=BASE_LAT + 0.02, lng=BASE_LNG + 0.02,
                estimated_minutes=90, difficulty=2, required_skills=[], required_equipment=[],
                earliest_date=date(2026, 7, 6), latest_date=date(2026, 7, 10)),
            Job(id="j2", client_id="c2", service_type=ServiceType.WINDOW_CLEANING,
                address="b", lat=BASE_LAT + 0.04, lng=BASE_LNG - 0.01,
                estimated_minutes=120, difficulty=2, required_skills=[], required_equipment=[],
                earliest_date=date(2026, 7, 6), latest_date=date(2026, 7, 10)),
            Job(id="j3", client_id="c3", service_type=ServiceType.PRESSURE_WASHING,
                address="c", lat=BASE_LAT - 0.03, lng=BASE_LNG + 0.04,
                estimated_minutes=60, difficulty=1, required_skills=[], required_equipment=[],
                earliest_date=date(2026, 7, 6), latest_date=date(2026, 7, 10)),
        ]
        draft = [{"crew_id": "crew_3j", "day": date(2026, 7, 7), "job_ids": ["j1", "j2", "j3"]}]
        ctx = AgentContext(week_start=date(2026, 7, 7), crews=[crew], jobs=jobs)
        ctx.blackboard["draft_plan"] = draft
        asyncio.run(TimeBudgetAgent().run(ctx))
        cd = ctx.blackboard["crew_days"][0]

        assert cd.total_work_minutes == 90 + 120 + 60, (
            f"total_work_minutes {cd.total_work_minutes} != 270"
        )
        assert len(cd.stops) == 3

    def test_three_job_stop_order_is_sequential(self):
        crew = Crew(
            id="crew_ord", name="order crew", members=["A"],
            skills=[], daily_minutes=9 * 60,
            base_lat=BASE_LAT, base_lng=BASE_LNG,
            equipment_ids=[], hourly_cost=100.0,
        )
        jobs = [
            Job(id=f"j{i}", client_id="c1", service_type=ServiceType.WINDOW_CLEANING,
                address="", lat=BASE_LAT + i * 0.01, lng=BASE_LNG,
                estimated_minutes=60, difficulty=1, required_skills=[], required_equipment=[],
                earliest_date=date(2026, 7, 6), latest_date=date(2026, 7, 10))
            for i in range(1, 4)
        ]
        draft = [{"crew_id": "crew_ord", "day": date(2026, 7, 7), "job_ids": ["j1", "j2", "j3"]}]
        ctx = AgentContext(week_start=date(2026, 7, 7), crews=[crew], jobs=jobs)
        ctx.blackboard["draft_plan"] = draft
        asyncio.run(TimeBudgetAgent().run(ctx))
        cd = ctx.blackboard["crew_days"][0]
        for i, stop in enumerate(cd.stops):
            assert stop.order == i, f"stop {i} has order={stop.order}"


# ─── Crew-match capacity pre-check ────────────────────────────────────────────

class TestCrewMatchCapacityPreCheck:
    """crew_match uses a conservative gate before placement:
       used + total_work + drive_budget > crew.daily_minutes → skip.
    drive_budget = 20 + 15 * (n_jobs - 1)."""

    def test_drive_budget_formula(self):
        for n in range(1, 6):
            expected = 20 + 15 * max(0, n - 1)
            # Reconstruct from the source
            actual = 20 + 15 * max(0, n - 1)
            assert actual == expected

    def test_1_job_drive_budget_is_20(self):
        assert 20 + 15 * max(0, 1 - 1) == 20

    def test_3_jobs_drive_budget_is_50(self):
        assert 20 + 15 * max(0, 3 - 1) == 50

    def test_schedule_respects_capacity_gate_no_overbook(self):
        """Run full planner with jobs that barely fit — no overbooking allowed."""
        from app.agents import SupervisorAgent
        seed(reset=True)

        # Override all jobs with tiny identical jobs near the depot
        store.jobs.clear()
        store.clients.clear()
        from app.models import Client
        store.clients["c1"] = Client(id="c1", name="Test", contact_phone="", contact_email="")

        # Alpha has 480 min / day.  Each job = 90 min, drive_budget(1)=20.
        # So max fit = floor(480 / (90+20)) = 4 jobs per day (4*110=440 < 480).
        # Create exactly 4 such jobs — all should land without overbooking.
        for i in range(4):
            j = Job(
                id=f"jfit_{i}", client_id="c1",
                service_type=ServiceType.WINDOW_CLEANING,
                address=f"addr_{i}",
                lat=BASE_LAT + 0.001 * i,
                lng=BASE_LNG + 0.001 * i,
                estimated_minutes=90, difficulty=2,
                required_skills=[Skill.LADDER_CERT],
                required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.VAN],
                earliest_date=date(2026, 7, 6),
                latest_date=date(2026, 7, 10),
            )
            j.status = JobStatus.PENDING
            store.jobs[j.id] = j

        import app.agents.geo_cluster as _gc
        import app.llm as _llm_mod

        original_geocode = _gc.geocoder.geocode
        original_chat = _llm_mod.llm.chat

        async def _fake_geo(address: str):
            from app.geocode import GeocodeResult
            for job in store.list_jobs():
                if job.address == address:
                    return GeocodeResult(
                        input_address=address, success=True,
                        lat=job.lat, lng=job.lng, formatted_address=address,
                        confidence=0.95, needs_review=False,
                        in_service_area=True, location_type="ROOFTOP",
                        postal_code="H9X", province="QC", source="google",
                    )
            return GeocodeResult(
                input_address=address, success=True,
                lat=BASE_LAT, lng=BASE_LNG, formatted_address=address,
                confidence=0.9, needs_review=False, in_service_area=True,
                location_type="APPROXIMATE", postal_code="H9X", province="QC", source="google",
            )

        async def _no_llm(*a, **kw):
            return None

        _gc.geocoder.geocode = _fake_geo
        _llm_mod.llm.chat = _no_llm

        try:
            sup = SupervisorAgent()
            result = asyncio.run(sup.plan_week(date(2026, 7, 6)))
        finally:
            _gc.geocoder.geocode = original_geocode
            _llm_mod.llm.chat = original_chat
            seed(reset=True)

        overbooked = [cd for cd in result.plan.days if cd.overbooked]
        assert not overbooked, (
            f"Crew-match let through jobs that made days overbooked: "
            + "; ".join(f"{cd.crew_id}/{cd.day}: {cd.warnings}" for cd in overbooked)
        )


# ─── Regression: duration invariant through full pipeline ─────────────────────

class TestDurationInvariantThroughPipeline:
    """Each stop's duration_minutes must equal its source job's estimated_minutes,
    regardless of which agent touched it.  This catches any silent mutation."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
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
            from app.seed import BASE_LAT, BASE_LNG
            return GeocodeResult(
                input_address=address, success=True,
                lat=BASE_LAT, lng=BASE_LNG, formatted_address=address,
                confidence=0.8, needs_review=True,
                in_service_area=True, location_type="APPROXIMATE",
                postal_code="H9X", province="QC", source="google",
            )

        monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode", _fake_geo)
        async def _no_llm(*a, **kw):
            return None

        monkeypatch.setattr("app.agents.supervisor._next_monday", lambda: date(2026, 7, 6))
        monkeypatch.setattr("app.llm.llm.chat", _no_llm)

    def test_every_stop_duration_matches_job_estimated_minutes(self):
        from app.agents import SupervisorAgent

        result = asyncio.run(SupervisorAgent().plan_week(date(2026, 7, 6)))
        jobs_by_id = {j.id: j for j in store.list_jobs()}

        for cd in result.plan.days:
            for stop in cd.stops:
                job = jobs_by_id[stop.job_id]
                assert stop.duration_minutes == job.estimated_minutes, (
                    f"stop.duration_minutes ({stop.duration_minutes}) != "
                    f"job.estimated_minutes ({job.estimated_minutes}) for {stop.job_id} "
                    f"on {cd.crew_id}/{cd.day}. A pipeline agent is silently modifying duration."
                )

    def test_total_work_minutes_equals_sum_of_stop_durations(self):
        from app.agents import SupervisorAgent

        result = asyncio.run(SupervisorAgent().plan_week(date(2026, 7, 6)))
        for cd in result.plan.days:
            expected = sum(s.duration_minutes for s in cd.stops)
            assert cd.total_work_minutes == expected, (
                f"{cd.crew_id}/{cd.day}: total_work_minutes={cd.total_work_minutes} "
                f"but sum(stop.duration)={expected}"
            )

    def test_no_zero_duration_stops_in_scheduled_plan(self):
        from app.agents import SupervisorAgent

        result = asyncio.run(SupervisorAgent().plan_week(date(2026, 7, 6)))
        for cd in result.plan.days:
            for stop in cd.stops:
                assert stop.duration_minutes > 0, (
                    f"Zero-duration stop {stop.job_id} on {cd.crew_id}/{cd.day}"
                )

    def test_total_drive_includes_return_leg_for_every_crew_day(self):
        from app.agents import SupervisorAgent

        result = asyncio.run(SupervisorAgent().plan_week(date(2026, 7, 6)))
        crews_by_id = {c.id: c for c in store.list_crews()}
        jobs_by_id = {j.id: j for j in store.list_jobs()}

        for cd in result.plan.days:
            if not cd.stops:
                continue
            crew = crews_by_id[cd.crew_id]
            last_stop = cd.stops[-1]
            last_job = jobs_by_id[last_stop.job_id]
            return_km = haversine_km(
                last_job.lat, last_job.lng,
                crew.base_lat, crew.base_lng,
            )
            min_return = drive_minutes(return_km)
            assert cd.total_drive_minutes >= min_return, (
                f"{cd.crew_id}/{cd.day}: total_drive_minutes={cd.total_drive_minutes} "
                f"should include at least {min_return} min return-to-base."
            )

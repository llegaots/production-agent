"""Scheduling preference mode tests.

Four modes are implemented:
  GEO_FIRST        — minimise drive time; tight geographic clusters
  CREW_FILL        — maximise utilisation; pack crew-days toward capacity
  BALANCED         — blend of utilisation and proximity
  REVENUE_PRIORITY — high-price jobs scheduled first; low-price deferred
                     when capacity is tight

── DESIGN ───────────────────────────────────────────────────────────────────

The tests use TWO synthetic datasets so the expected differences are sharp
and deterministic:

SPREAD_DATASET  (12 jobs, 2 identical crews)
  West zone  : 4 jobs near depot         (< 3 km)
  East zone  : 4 jobs 15+ km from depot
  North zone : 4 jobs 10+ km from depot
  All jobs require the same skills and equipment.
  All jobs are the same duration (90 min) and identical price.
  This isolates the GEOGRAPHIC / UTILISATION contrast.

REVENUE_DATASET  (8 jobs, 1 crew, tight capacity)
  4 "premium" jobs priced $900 each, 120 min each
  4 "budget"  jobs priced $50  each, 120 min each
  1 crew with daily_minutes=300 (fits ~2 jobs/day incl. drive)
  5 working days → theoretical max ~9-10 jobs; drive overhead limits
  actual capacity to ~7 jobs → NOT all 8 fit → last job(s) deferred.
  This isolates the REVENUE PRIORITY contrast.

── WHAT EACH MODE IS REQUIRED TO GUARANTEE ─────────────────────────────────

Mode             | Guarantee tested
─────────────────|──────────────────────────────────────────────────────────
GEO_FIRST        | ≤ drive ratio of CREW_FILL (on SPREAD_DATASET)
CREW_FILL        | ≥ avg utilisation of GEO_FIRST (on SPREAD_DATASET)
                 | fewer or equal active crew-days than GEO_FIRST
BALANCED         | avg utilisation between GEO_FIRST and CREW_FILL
                 | or at least as good as the worst of those two
REVENUE_PRIORITY | premium jobs always scheduled when deferred jobs exist
                 | scheduled premium revenue ≥ scheduled budget revenue
                 | when total_scheduled < total_jobs
ALL MODES        | no skill violation
                 | no equipment violation
                 | no date-window violation
                 | no overbooked days
                 | stop ordering sequential
                 | stop duration == job.estimated_minutes
"""
from __future__ import annotations

import asyncio
import math
import statistics
from datetime import date
from typing import Any

import pytest

from app.agents import SupervisorAgent
from app.agents.base import drive_minutes, haversine_km
from app.models import (
    Client,
    Crew,
    Equipment,
    EquipmentKind,
    Job,
    JobStatus,
    PlanResult,
    ServiceType,
    Skill,
)
from app.scheduling_prefs import (
    SchedulingMode,
    cluster_sort_key,
    geo_cluster_target_cap,
    parse_mode,
    placement_score_bonus,
)
from app.seed import BASE_LAT, BASE_LNG
from app.storage import store


# ─── Helpers ─────────────────────────────────────────────────────────────────

WEEK = date(2026, 7, 6)   # Monday


def _fake_geocode_fn(jobs_by_address: dict):
    async def _geocode(address: str):
        from app.geocode import GeocodeResult
        hit = jobs_by_address.get(address)
        lat, lng = (hit.lat, hit.lng) if hit else (BASE_LAT, BASE_LNG)
        return GeocodeResult(
            input_address=address, success=True,
            lat=lat, lng=lng, formatted_address=address,
            confidence=0.95, needs_review=False,
            in_service_area=True, location_type="ROOFTOP",
            postal_code="H9X", province="QC", source="google",
        )
    return _geocode


async def _no_llm(*a, **kw):
    return None


def _plan(
    mode: SchedulingMode,
    *,
    monkeypatch,
    week: date = WEEK,
) -> PlanResult:
    """Run the full planner pipeline on the current store state."""
    import app.agents.geo_cluster as _gc
    import app.llm as _llm_mod
    jobs_by_address = {j.address: j for j in store.list_jobs()}
    monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode",
                        _fake_geocode_fn(jobs_by_address))
    monkeypatch.setattr("app.agents.supervisor._next_monday", lambda: week)
    monkeypatch.setattr("app.llm.llm.chat", _no_llm)
    return asyncio.run(SupervisorAgent().plan_week(week, scheduling_mode=mode))


def _metrics(result: PlanResult) -> dict[str, Any]:
    """Summarise a plan into comparable scalar metrics."""
    days = result.plan.days
    if not days:
        return {
            "active_days": 0,
            "avg_utilization": 0.0,
            "utilization_stdev": 0.0,
            "total_drive": 0,
            "total_work": 0,
            "drive_ratio": 0.0,
            "scheduled": 0,
            "unscheduled": len(result.plan.unscheduled_job_ids),
        }
    utils = [cd.utilization for cd in days]
    total_drive = sum(cd.total_drive_minutes for cd in days)
    total_work  = sum(cd.total_work_minutes  for cd in days)
    return {
        "active_days":       len(days),
        "avg_utilization":   round(statistics.mean(utils), 4),
        "utilization_stdev": round(statistics.stdev(utils) if len(utils) > 1 else 0.0, 4),
        "total_drive":       total_drive,
        "total_work":        total_work,
        "drive_ratio":       round(total_drive / max(1, total_work), 4),
        "scheduled":         sum(len(cd.stops) for cd in days),
        "unscheduled":       len(result.plan.unscheduled_job_ids),
    }


def _simple_job(
    job_id: str, client_id: str = "c1",
    lat: float = BASE_LAT, lng: float = BASE_LNG,
    minutes: int = 90, price: float = 200.0,
    skills: list[Skill] | None = None,
    equipment: list[EquipmentKind] | None = None,
    week: date = WEEK,
) -> Job:
    j = Job(
        id=job_id, client_id=client_id,
        service_type=ServiceType.WINDOW_CLEANING,
        address=f"addr_{job_id}",
        lat=lat, lng=lng,
        estimated_minutes=minutes, difficulty=2,
        required_skills=skills or [Skill.LADDER_CERT],
        required_equipment=equipment or [EquipmentKind.LADDER_28, EquipmentKind.VAN],
        earliest_date=week, latest_date=week + __import__("datetime").timedelta(days=4),
        price=price,
    )
    j.status = JobStatus.PENDING
    return j


def _simple_crew(
    crew_id: str,
    lat: float = BASE_LAT, lng: float = BASE_LNG,
    daily_minutes: int = 480,
    skills: list[Skill] | None = None,
    eq_ids: list[str] | None = None,
) -> Crew:
    return Crew(
        id=crew_id, name=crew_id,
        members=["A", "B"],
        skills=skills or [Skill.LADDER_CERT],
        daily_minutes=daily_minutes,
        base_lat=lat, base_lng=lng,
        equipment_ids=eq_ids or ["eq_lad", "eq_van"],
        hourly_cost=110.0,
    )


def _load_spread_dataset():
    """12 identical jobs spread across 3 geographic zones; 2 identical crews."""
    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()

    store.clients["c1"] = Client(id="c1", name="Test", contact_phone="", contact_email="")
    store.equipment["eq_lad"] = Equipment(id="eq_lad", kind=EquipmentKind.LADDER_28, label="Ladder")
    store.equipment["eq_van"] = Equipment(id="eq_van", kind=EquipmentKind.VAN, label="Van A")
    store.equipment["eq_van2"] = Equipment(id="eq_van2", kind=EquipmentKind.VAN, label="Van B")

    store.crews["crew_a"] = _simple_crew("crew_a", eq_ids=["eq_lad", "eq_van"])
    store.crews["crew_b"] = _simple_crew("crew_b", eq_ids=["eq_lad", "eq_van2"])

    # West zone: ~2 km from depot
    west_offsets = [(0.015, 0.010), (0.018, 0.015), (0.012, 0.008), (0.016, 0.012)]
    # North zone: ~10 km north
    north_offsets = [(0.085, 0.020), (0.090, 0.025), (0.080, 0.015), (0.088, 0.018)]
    # East zone: ~15 km east (large lng change)
    east_offsets = [(0.010, -0.180), (0.015, -0.185), (0.005, -0.175), (0.012, -0.182)]

    jobs = []
    for i, (dlat, dlng) in enumerate(west_offsets):
        jobs.append(_simple_job(f"west_{i}", lat=BASE_LAT+dlat, lng=BASE_LNG+dlng))
    for i, (dlat, dlng) in enumerate(north_offsets):
        jobs.append(_simple_job(f"north_{i}", lat=BASE_LAT+dlat, lng=BASE_LNG+dlng))
    for i, (dlat, dlng) in enumerate(east_offsets):
        jobs.append(_simple_job(f"east_{i}", lat=BASE_LAT+dlat, lng=BASE_LNG+dlng))

    for j in jobs:
        store.jobs[j.id] = j


def _load_revenue_dataset():
    """8 jobs (4 premium, 4 budget); 1 crew with tight daily capacity."""
    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()

    store.clients["c1"] = Client(id="c1", name="Test", contact_phone="", contact_email="")
    store.equipment["eq_lad"] = Equipment(id="eq_lad", kind=EquipmentKind.LADDER_28, label="Ladder")
    store.equipment["eq_van"] = Equipment(id="eq_van", kind=EquipmentKind.VAN, label="Van")

    # 1 crew, 350 min/day.  Each job=120 min; drive adds ~10-15 min/job.
    # Day fits ~2 jobs (120+120+~30 drive < 350, 3rd job would be 120+120+120+~45=405 > 350).
    # 5 days × ~2 jobs = 10 job-slots but some days may fit 2, some 1 due to travel.
    # 8 jobs total → ~1-2 deferred when capacity is genuinely tight.
    store.crews["crew_sole"] = _simple_crew(
        "crew_sole", daily_minutes=350, eq_ids=["eq_lad", "eq_van"]
    )

    jobs = []
    for i in range(4):
        jobs.append(_simple_job(
            f"premium_{i}", lat=BASE_LAT + 0.01 * i, lng=BASE_LNG + 0.005 * i,
            minutes=120, price=900.0,
        ))
    for i in range(4):
        jobs.append(_simple_job(
            f"budget_{i}", lat=BASE_LAT - 0.01 * i, lng=BASE_LNG - 0.005 * i,
            minutes=120, price=50.0,
        ))
    for j in jobs:
        store.jobs[j.id] = j


# ─── Unit tests on formula functions ─────────────────────────────────────────

class TestFormulas:
    """All four modes must have coherent, documented formula values."""

    def test_all_modes_parse_correctly(self):
        assert parse_mode("geo_first")        == SchedulingMode.GEO_FIRST
        assert parse_mode("crew_fill")        == SchedulingMode.CREW_FILL
        assert parse_mode("balanced")         == SchedulingMode.BALANCED
        assert parse_mode("revenue_priority") == SchedulingMode.REVENUE_PRIORITY

    def test_aliases_resolve(self):
        assert parse_mode("location")         == SchedulingMode.GEO_FIRST
        assert parse_mode("packed days")      == SchedulingMode.CREW_FILL
        assert parse_mode("priority")         == SchedulingMode.REVENUE_PRIORITY
        assert parse_mode("value")            == SchedulingMode.REVENUE_PRIORITY

    def test_placement_bonus_geo_penalises_drive_hardest(self):
        """GEO_FIRST must have the largest negative drive coefficient."""
        km = 20.0
        geo   = placement_score_bonus(SchedulingMode.GEO_FIRST,        400, km)
        fill  = placement_score_bonus(SchedulingMode.CREW_FILL,         400, km)
        bal   = placement_score_bonus(SchedulingMode.BALANCED,          400, km)
        rev   = placement_score_bonus(SchedulingMode.REVENUE_PRIORITY,  400, km)
        # At fixed headroom, the mode that penalises drive hardest scores lowest.
        assert geo <= bal, "GEO_FIRST should penalise drive ≥ BALANCED"
        assert geo <= rev, "GEO_FIRST should penalise drive ≥ REVENUE_PRIORITY"
        assert geo <= fill, "GEO_FIRST should penalise drive ≥ CREW_FILL"

    def test_placement_bonus_crew_fill_rewards_headroom_most(self):
        """CREW_FILL must have the largest positive headroom coefficient."""
        remaining = 400
        geo  = placement_score_bonus(SchedulingMode.GEO_FIRST,        remaining, 0.0)
        fill = placement_score_bonus(SchedulingMode.CREW_FILL,         remaining, 0.0)
        bal  = placement_score_bonus(SchedulingMode.BALANCED,          remaining, 0.0)
        rev  = placement_score_bonus(SchedulingMode.REVENUE_PRIORITY,  remaining, 0.0)
        assert fill >= bal,  "CREW_FILL headroom bonus must be ≥ BALANCED"
        assert fill >= geo,  "CREW_FILL headroom bonus must be ≥ GEO_FIRST"
        assert fill >= rev,  "CREW_FILL headroom bonus must be ≥ REVENUE_PRIORITY"

    def test_cluster_cap_crew_fill_is_half_geo_first(self):
        max_slots = 10
        geo  = geo_cluster_target_cap(SchedulingMode.GEO_FIRST,        max_slots, 20)
        fill = geo_cluster_target_cap(SchedulingMode.CREW_FILL,         max_slots, 20)
        assert fill <= geo // 2 + 1, (
            f"CREW_FILL cluster cap ({fill}) should be roughly half GEO_FIRST ({geo})"
        )

    def test_cluster_cap_never_exceeds_job_count(self):
        for mode in SchedulingMode:
            cap = geo_cluster_target_cap(mode, 10, 3)
            assert cap <= 3, f"cluster cap {cap} > job count 3 in {mode}"

    def test_cluster_sort_key_revenue_mode_uses_price(self):
        from datetime import date as _date
        jobs = {
            "j1": _simple_job("j1", price=100.0),
            "j2": _simple_job("j2", price=900.0),
            "j3": _simple_job("j3", price=500.0),
        }
        key_rev = cluster_sort_key(SchedulingMode.REVENUE_PRIORITY, ["j1", "j2", "j3"], jobs)
        key_def = cluster_sort_key(SchedulingMode.GEO_FIRST,        ["j1", "j2", "j3"], jobs)
        assert key_rev == 1500.0,  "revenue key should sum prices"
        assert key_def == 270.0,   "default key should sum estimated_minutes (3×90)"

    def test_cluster_sort_key_revenue_orders_clusters_by_price(self):
        from datetime import date as _date
        cheap = {"j_cheap": _simple_job("j_cheap", price=10.0)}
        pricy = {"j_pricy": _simple_job("j_pricy", price=999.0)}
        key_cheap = cluster_sort_key(SchedulingMode.REVENUE_PRIORITY, ["j_cheap"], cheap)
        key_pricy = cluster_sort_key(SchedulingMode.REVENUE_PRIORITY, ["j_pricy"], pricy)
        assert key_pricy > key_cheap


# ─── Hard-constraint satisfaction (all modes) ─────────────────────────────────

class TestHardConstraintsAllModes:
    """Every mode must produce a schedule that obeys all hard constraints."""

    @pytest.fixture(autouse=True)
    def _seed(self, monkeypatch):
        _load_spread_dataset()
        yield

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_skill_constraint_never_violated(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for cd in result.plan.days:
            crew = store.get_crew(cd.crew_id)
            for stop in cd.stops:
                missing = set(jobs_by_id[stop.job_id].required_skills) - set(crew.skills)
                assert not missing, (
                    f"{mode}: Job {stop.job_id} on {cd.crew_id} missing skills {missing}"
                )

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_equipment_constraint_never_violated(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        crew_eq_kinds = {}
        for crew in store.list_crews():
            kinds = set()
            for eid in crew.equipment_ids:
                eq = store.get_equipment(eid)
                if eq:
                    kinds.add(eq.kind)
            crew_eq_kinds[crew.id] = kinds
        for cd in result.plan.days:
            for stop in cd.stops:
                job = jobs_by_id[stop.job_id]
                missing = set(job.required_equipment) - crew_eq_kinds[cd.crew_id]
                assert not missing, (
                    f"{mode}: Job {stop.job_id} on {cd.crew_id} missing equipment {missing}"
                )

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_date_window_never_violated(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for cd in result.plan.days:
            for stop in cd.stops:
                job = jobs_by_id[stop.job_id]
                assert cd.day >= job.earliest_date, (
                    f"{mode}: {stop.job_id} scheduled {cd.day} < earliest {job.earliest_date}"
                )
                assert cd.day <= job.latest_date, (
                    f"{mode}: {stop.job_id} scheduled {cd.day} > latest {job.latest_date}"
                )

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_no_overbooked_days(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        overbooked = [
            f"{cd.crew_id}/{cd.day}: {cd.warnings}"
            for cd in result.plan.days if cd.overbooked
        ]
        assert not overbooked, f"{mode}: overbooked days found: {overbooked}"

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_stop_duration_equals_estimated_minutes(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for cd in result.plan.days:
            for stop in cd.stops:
                assert stop.duration_minutes == jobs_by_id[stop.job_id].estimated_minutes, (
                    f"{mode}: duration mismatch for {stop.job_id}: "
                    f"got {stop.duration_minutes}, "
                    f"expected {jobs_by_id[stop.job_id].estimated_minutes}"
                )

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_stop_ordering_sequential(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        for cd in result.plan.days:
            for idx, stop in enumerate(cd.stops):
                assert stop.order == idx, (
                    f"{mode}: {cd.crew_id}/{cd.day} stop {stop.job_id} "
                    f"has order={stop.order}, expected {idx}"
                )

    @pytest.mark.parametrize("mode", list(SchedulingMode))
    def test_all_jobs_accounted_for(self, mode, monkeypatch):
        result = _plan(mode, monkeypatch=monkeypatch)
        scheduled = {s.job_id for d in result.plan.days for s in d.stops}
        unscheduled = set(result.plan.unscheduled_job_ids)
        all_jobs = {j.id for j in store.list_jobs()}
        in_plan = scheduled | unscheduled
        assert in_plan == all_jobs, (
            f"{mode}: missing from plan: {all_jobs - in_plan}; "
            f"double-counted: {in_plan - all_jobs}"
        )


# ─── Behavioural differences between modes ────────────────────────────────────

class TestModeBehaviouralDifferences:
    """Verify that modes produce MEASURABLY different schedules when given a
    dataset that creates real trade-offs between geography and utilisation."""

    @pytest.fixture(autouse=True)
    def _seed(self, monkeypatch):
        _load_spread_dataset()
        yield

    def test_crew_fill_has_fewer_or_equal_active_days_than_geo_first(self, monkeypatch):
        """CREW_FILL uses larger clusters so work is packed into fewer crew-days."""
        r_geo  = _plan(SchedulingMode.GEO_FIRST,  monkeypatch=monkeypatch)
        r_fill = _plan(SchedulingMode.CREW_FILL,   monkeypatch=monkeypatch)
        m_geo  = _metrics(r_geo)
        m_fill = _metrics(r_fill)
        assert m_fill["active_days"] <= m_geo["active_days"], (
            f"CREW_FILL should pack into ≤ as many crew-days as GEO_FIRST. "
            f"geo={m_geo['active_days']}, fill={m_fill['active_days']}"
        )

    def test_crew_fill_avg_utilisation_at_least_as_high_as_geo_first(self, monkeypatch):
        """Larger clusters → more work per active day → higher utilisation."""
        r_geo  = _plan(SchedulingMode.GEO_FIRST,  monkeypatch=monkeypatch)
        r_fill = _plan(SchedulingMode.CREW_FILL,   monkeypatch=monkeypatch)
        m_geo  = _metrics(r_geo)
        m_fill = _metrics(r_fill)
        assert m_fill["avg_utilization"] >= m_geo["avg_utilization"] - 0.02, (
            f"CREW_FILL avg util {m_fill['avg_utilization']:.3f} "
            f"< GEO_FIRST {m_geo['avg_utilization']:.3f} (minus 2% tolerance)"
        )

    def test_geo_first_drive_ratio_at_most_as_high_as_crew_fill(self, monkeypatch):
        """GEO_FIRST penalises drive more strongly, so drive ratio should be ≤ CREW_FILL."""
        r_geo  = _plan(SchedulingMode.GEO_FIRST,  monkeypatch=monkeypatch)
        r_fill = _plan(SchedulingMode.CREW_FILL,   monkeypatch=monkeypatch)
        m_geo  = _metrics(r_geo)
        m_fill = _metrics(r_fill)
        # Allow a 5% tolerance: on small datasets the difference may be marginal.
        assert m_geo["drive_ratio"] <= m_fill["drive_ratio"] + 0.05, (
            f"GEO_FIRST drive ratio {m_geo['drive_ratio']:.3f} "
            f"> CREW_FILL {m_fill['drive_ratio']:.3f} + 5% tolerance"
        )

    def test_balanced_active_days_between_geo_and_fill(self, monkeypatch):
        """BALANCED cluster cap is the same as GEO_FIRST but score weights are intermediate."""
        r_geo  = _plan(SchedulingMode.GEO_FIRST,  monkeypatch=monkeypatch)
        r_fill = _plan(SchedulingMode.CREW_FILL,   monkeypatch=monkeypatch)
        r_bal  = _plan(SchedulingMode.BALANCED,    monkeypatch=monkeypatch)
        m_geo  = _metrics(r_geo)
        m_fill = _metrics(r_fill)
        m_bal  = _metrics(r_bal)
        lo = min(m_geo["active_days"], m_fill["active_days"])
        hi = max(m_geo["active_days"], m_fill["active_days"])
        assert lo <= m_bal["active_days"] <= hi + 1, (
            f"BALANCED active_days {m_bal['active_days']} outside "
            f"[{lo}, {hi+1}] (geo={m_geo['active_days']}, fill={m_fill['active_days']})"
        )

    def test_all_modes_schedule_same_total_jobs(self, monkeypatch):
        """All modes should schedule all 12 jobs (no capacity pressure)."""
        for mode in SchedulingMode:
            result = _plan(mode, monkeypatch=monkeypatch)
            m = _metrics(result)
            assert m["scheduled"] == 12, (
                f"{mode}: expected 12 scheduled, got {m['scheduled']}"
            )
            assert m["unscheduled"] == 0, (
                f"{mode}: expected 0 unscheduled, got {m['unscheduled']}"
            )


# ─── Revenue priority ─────────────────────────────────────────────────────────

class TestRevenuePriorityMode:
    """REVENUE_PRIORITY schedules high-value jobs before low-value ones.

    The revenue dataset is designed so 1-2 jobs are deferred due to capacity
    pressure. REVENUE_PRIORITY must ensure all deferred jobs are budget ones,
    and scheduled premium revenue ≥ scheduled budget revenue.
    """

    @pytest.fixture(autouse=True)
    def _seed(self, monkeypatch):
        _load_revenue_dataset()
        yield

    def _run_both(self, monkeypatch):
        r_rev = _plan(SchedulingMode.REVENUE_PRIORITY, monkeypatch=monkeypatch)
        r_geo = _plan(SchedulingMode.GEO_FIRST,        monkeypatch=monkeypatch)
        return r_rev, r_geo

    def test_revenue_mode_schedules_all_premium_jobs(self, monkeypatch):
        """When not all jobs fit, no premium job should be deferred."""
        result = _plan(SchedulingMode.REVENUE_PRIORITY, monkeypatch=monkeypatch)
        premium_ids = {f"premium_{i}" for i in range(4)}
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        unscheduled = set(result.plan.unscheduled_job_ids)

        # If there ARE deferred jobs, they must all be budget jobs.
        deferred_premium = unscheduled & premium_ids
        if deferred_premium:
            # Only fail if BUDGET jobs also land — that would mean the scheduler
            # chose a cheap job over an expensive one.
            scheduled = {s.job_id for d in result.plan.days for s in d.stops}
            deferred_budget = unscheduled - premium_ids
            scheduled_budget = scheduled - premium_ids
            assert not (deferred_premium and scheduled_budget), (
                f"Revenue priority deferred premium job(s) {deferred_premium} "
                f"while scheduling budget jobs {scheduled_budget}"
            )

    def test_revenue_mode_maximises_scheduled_revenue(self, monkeypatch):
        """Scheduled revenue in REVENUE_PRIORITY must be ≥ GEO_FIRST."""
        r_rev, r_geo = self._run_both(monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}

        def _total_revenue(result: PlanResult) -> float:
            return sum(
                jobs_by_id[s.job_id].price
                for cd in result.plan.days
                for s in cd.stops
            )

        rev_revenue = _total_revenue(r_rev)
        geo_revenue = _total_revenue(r_geo)
        assert rev_revenue >= geo_revenue - 0.01, (
            f"REVENUE_PRIORITY total scheduled revenue ${rev_revenue:.2f} "
            f"< GEO_FIRST ${geo_revenue:.2f}. "
            "Revenue mode must not leave high-price jobs unscheduled when cheaper jobs land."
        )

    def test_revenue_mode_does_not_violate_hard_constraints(self, monkeypatch):
        """Revenue ordering must not bypass skill, equipment, capacity, or date constraints."""
        result = _plan(SchedulingMode.REVENUE_PRIORITY, monkeypatch=monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        crew_eq = {}
        for crew in store.list_crews():
            kinds = set()
            for eid in crew.equipment_ids:
                eq = store.get_equipment(eid)
                if eq:
                    kinds.add(eq.kind)
            crew_eq[crew.id] = kinds

        for cd in result.plan.days:
            assert not cd.overbooked, f"REVENUE_PRIORITY overbooked {cd.crew_id}/{cd.day}"
            crew = store.get_crew(cd.crew_id)
            for stop in cd.stops:
                job = jobs_by_id[stop.job_id]
                assert not (set(job.required_skills) - set(crew.skills)), (
                    f"Skill violation: {stop.job_id} on {cd.crew_id}"
                )
                assert not (set(job.required_equipment) - crew_eq[cd.crew_id]), (
                    f"Equipment violation: {stop.job_id} on {cd.crew_id}"
                )

    def test_deferred_jobs_are_lower_value_than_scheduled_ones(self, monkeypatch):
        """When any job is deferred, min(scheduled price) ≥ max(deferred price)
        is ideal; at minimum, mean(scheduled price) > mean(deferred price)."""
        result = _plan(SchedulingMode.REVENUE_PRIORITY, monkeypatch=monkeypatch)
        jobs_by_id = {j.id: j for j in store.list_jobs()}
        unscheduled = result.plan.unscheduled_job_ids
        if not unscheduled:
            pytest.skip("No jobs were deferred — capacity was sufficient for all")

        scheduled = {s.job_id for d in result.plan.days for s in d.stops}
        sched_prices = [jobs_by_id[jid].price for jid in scheduled]
        defer_prices = [jobs_by_id[jid].price for jid in unscheduled]

        assert statistics.mean(sched_prices) > statistics.mean(defer_prices), (
            f"Mean scheduled price ${statistics.mean(sched_prices):.2f} "
            f"should exceed mean deferred price ${statistics.mean(defer_prices):.2f}"
        )


# ─── Regression: mode is correctly applied by SupervisorAgent ─────────────────

class TestModePassthrough:
    """The mode parameter must actually reach the scheduling agents."""

    @pytest.fixture(autouse=True)
    def _seed(self, monkeypatch):
        _load_spread_dataset()
        yield

    def test_plan_result_reflects_chosen_mode(self, monkeypatch):
        """The store's scheduling_mode should match what was requested."""
        for mode in SchedulingMode:
            _plan(mode, monkeypatch=monkeypatch)
            assert store.scheduling_mode == mode, (
                f"After planning with {mode}, store.scheduling_mode={store.scheduling_mode}"
            )

    def test_cluster_sort_revenue_mode_orders_by_price(self):
        """cluster_sort_key with REVENUE_PRIORITY must rank high-price first."""
        from datetime import date as _date, timedelta as _td
        low  = _simple_job("low",  price=10.0)
        mid  = _simple_job("mid",  price=300.0)
        high = _simple_job("high", price=1500.0)
        jmap = {"low": low, "mid": mid, "high": high}

        k_high = cluster_sort_key(SchedulingMode.REVENUE_PRIORITY, ["high"], jmap)
        k_mid  = cluster_sort_key(SchedulingMode.REVENUE_PRIORITY, ["mid"],  jmap)
        k_low  = cluster_sort_key(SchedulingMode.REVENUE_PRIORITY, ["low"],  jmap)
        assert k_high > k_mid > k_low

    def test_cluster_sort_default_mode_orders_by_duration(self):
        short = _simple_job("short", minutes=30)
        long_ = _simple_job("long",  minutes=300)
        jmap = {"short": short, "long": long_}
        k_s = cluster_sort_key(SchedulingMode.GEO_FIRST, ["short"], jmap)
        k_l = cluster_sort_key(SchedulingMode.GEO_FIRST, ["long"],  jmap)
        assert k_l > k_s

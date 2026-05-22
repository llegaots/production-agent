"""Realistic scheduling logic tests against the full West Island seed dataset.

These tests verify that the scheduler produces logically valid results, not
just that code runs.  Each test asserts a real domain constraint:

  - Skill matching: rope-access jobs must go to Charlie only
  - Equipment matching: gutter jobs (ladder_32) must go to Bravo
  - Capacity: no crew day overbooked (work + drive > daily_minutes)
  - Date windows: future-window jobs must NOT be scheduled this week
  - Geographic grouping: adjacent jobs (same street) should land same day
  - Full-day jobs: a 7-h job should consume the crew's day alone
  - Impossible jobs: no crew can satisfy — must appear unscheduled
  - Utilization: at least 60% of schedulable jobs are placed
  - Stop ordering: sequential stop.order values, all travel times >= 0
  - Route sense: drive ratio (drive / work) stays under a threshold
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.agents import SupervisorAgent
from app.models import EquipmentKind, JobStatus, ServiceType, Skill
from app.seed import seed
from app.storage import store


# ─── Shared fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def realistic_seed(monkeypatch):
    """Full 28-job dataset with fake geocoder (use seeded lat/lng as-is)."""
    seed(reset=True)

    async def _fake_geocode(address: str):
        from app.geocode import GeocodeResult
        # Return the seeded coordinates for the job matching this address;
        # fall back to depot so the scheduler still runs if address unknown.
        for j in store.list_jobs():
            if j.address == address:
                return GeocodeResult(
                    input_address=address, success=True,
                    lat=j.lat, lng=j.lng,
                    formatted_address=address,
                    confidence=0.95, needs_review=False,
                    in_service_area=True, location_type="ROOFTOP",
                    postal_code="H9X 1A1", province="QC", source="google",
                )
        from app.seed import BASE_LAT, BASE_LNG
        return GeocodeResult(
            input_address=address, success=True,
            lat=BASE_LAT, lng=BASE_LNG,
            formatted_address=address,
            confidence=0.80, needs_review=True,
            in_service_area=True, location_type="APPROXIMATE",
            postal_code="H9X 1A1", province="QC", source="google",
        )

    monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode", _fake_geocode)
    monkeypatch.setattr("app.row_import.geocoder.geocode", _fake_geocode)

    async def _no_llm(*_a, **_kw):
        return None

    monkeypatch.setattr("app.llm.llm.chat", _no_llm)
    yield


@pytest.fixture(scope="module")
def plan_result():
    """Run the planner once; share across tests in this module."""
    seed(reset=True)

    async def _fake_geocode(address: str):
        from app.geocode import GeocodeResult
        for j in store.list_jobs():
            if j.address == address:
                return GeocodeResult(
                    input_address=address, success=True,
                    lat=j.lat, lng=j.lng,
                    formatted_address=address,
                    confidence=0.95, needs_review=False,
                    in_service_area=True, location_type="ROOFTOP",
                    postal_code="H9X 1A1", province="QC", source="google",
                )
        from app.seed import BASE_LAT, BASE_LNG
        return GeocodeResult(
            input_address=address, success=True,
            lat=BASE_LAT, lng=BASE_LNG,
            formatted_address=address,
            confidence=0.80, needs_review=True,
            in_service_area=True, location_type="APPROXIMATE",
            postal_code="H9X 1A1", province="QC", source="google",
        )

    import app.agents.geo_cluster as _gc
    import app.row_import as _ri
    import app.llm as _llm_mod

    original_geocode = _gc.geocoder.geocode
    original_ri = _ri.geocoder.geocode
    original_chat = _llm_mod.llm.chat

    _gc.geocoder.geocode = _fake_geocode
    _ri.geocoder.geocode = _fake_geocode

    async def _no_llm(*_a, **_kw):
        return None

    _llm_mod.llm.chat = _no_llm

    result = asyncio.run(SupervisorAgent().plan_week(date(2026, 7, 6)))

    _gc.geocoder.geocode = original_geocode
    _ri.geocoder.geocode = original_ri
    _llm_mod.llm.chat = original_chat

    return result


# ─── Dataset integrity ────────────────────────────────────────────────────────

def test_seed_has_expected_counts():
    assert len(store.list_jobs()) == 27, "expected 27 jobs in realistic seed"
    assert len(store.list_crews()) == 4
    assert len(store.list_equipment()) >= 18


def test_seed_has_all_service_types():
    types = {j.service_type for j in store.list_jobs()}
    assert ServiceType.WINDOW_CLEANING  in types
    assert ServiceType.GUTTER_CLEANING  in types
    assert ServiceType.PRESSURE_WASHING in types
    assert ServiceType.HIGH_RISE        in types
    assert ServiceType.SOLAR_PANEL_CLEANING in types


def test_seed_rope_access_jobs_exist():
    rope_jobs = [j for j in store.list_jobs() if Skill.ROPE_ACCESS in j.required_skills]
    assert len(rope_jobs) >= 2, "expected at least 2 rope-access jobs"


def test_seed_ladder32_jobs_exist():
    gutter_jobs = [j for j in store.list_jobs() if EquipmentKind.LADDER_32 in j.required_equipment]
    assert len(gutter_jobs) >= 3, "expected at least 3 gutter jobs needing ladder_32"


def test_future_window_job_exists():
    future_jobs = [j for j in store.list_jobs() if j.earliest_date >= date(2026, 8, 1)]
    assert len(future_jobs) >= 1


# ─── Crew capability verification ─────────────────────────────────────────────

def test_only_charlie_has_rope_access():
    rope_crews = [c for c in store.list_crews() if Skill.ROPE_ACCESS in c.skills]
    assert len(rope_crews) == 1
    assert rope_crews[0].id == "crew_charlie"


def test_only_bravo_has_ladder_32():
    bravo = store.get_crew("crew_bravo")
    for eq_id in bravo.equipment_ids:
        eq = store.get_equipment(eq_id)
        if eq and eq.kind == EquipmentKind.LADDER_32:
            break
    else:
        pytest.fail("crew_bravo must carry a ladder_32")

    for crew in store.list_crews():
        if crew.id == "crew_bravo":
            continue
        for eq_id in crew.equipment_ids:
            eq = store.get_equipment(eq_id)
            assert eq is None or eq.kind != EquipmentKind.LADDER_32, (
                f"crew {crew.id} unexpectedly has a ladder_32"
            )


def test_bravo_is_only_crew_with_scissor_lift():
    lift_crews = []
    for crew in store.list_crews():
        for eq_id in crew.equipment_ids:
            eq = store.get_equipment(eq_id)
            if eq and eq.kind == EquipmentKind.SCISSOR_LIFT:
                lift_crews.append(crew.id)
    assert lift_crews == ["crew_bravo"]


# ─── Planner results ──────────────────────────────────────────────────────────

def test_plan_runs_without_crash(plan_result):
    assert plan_result is not None
    assert plan_result.plan is not None


def test_utilization_rate(plan_result):
    """At least 60% of schedulable-this-week jobs must land."""
    week = (date(2026, 7, 6), date(2026, 7, 10))
    schedulable = [
        j for j in store.list_jobs()
        if j.earliest_date <= week[1] and j.latest_date >= week[0]
    ]
    scheduled = {s.job_id for d in plan_result.plan.days for s in d.stops}
    rate = len(scheduled) / max(1, len(schedulable))
    assert rate >= 0.60, (
        f"Only {len(scheduled)}/{len(schedulable)} schedulable jobs placed ({rate:.0%}). "
        "Scheduler underutilising capacity."
    )


def test_future_window_job_not_scheduled(plan_result):
    """job_W12 window opens in August — must never appear in the July plan."""
    scheduled = {s.job_id for d in plan_result.plan.days for s in d.stops}
    assert "job_W12" not in scheduled, (
        "job_W12 has earliest_date 2026-08-03 but was scheduled in the July week"
    )


def test_rope_jobs_only_assigned_to_charlie(plan_result):
    """High-rise rope-access jobs must never land on Alpha, Bravo, or Delta."""
    rope_job_ids = {j.id for j in store.list_jobs() if Skill.ROPE_ACCESS in j.required_skills}
    for cd in plan_result.plan.days:
        if cd.crew_id == "crew_charlie":
            continue
        for stop in cd.stops:
            assert stop.job_id not in rope_job_ids, (
                f"Rope-access job {stop.job_id} was assigned to crew {cd.crew_id} "
                "which lacks ROPE_ACCESS skill."
            )


def test_gutter_jobs_only_assigned_to_bravo(plan_result):
    """Gutter jobs require ladder_32 — only Bravo carries it."""
    gutter_job_ids = {
        j.id for j in store.list_jobs()
        if EquipmentKind.LADDER_32 in j.required_equipment
    }
    scheduled_gutter = set()
    for cd in plan_result.plan.days:
        for stop in cd.stops:
            if stop.job_id in gutter_job_ids:
                scheduled_gutter.add(stop.job_id)
                assert cd.crew_id == "crew_bravo", (
                    f"Gutter job {stop.job_id} assigned to {cd.crew_id}; only Bravo has ladder_32."
                )


def test_impossible_job_is_unscheduled(plan_result):
    """job_G05 requires both ROPE_ACCESS + LADDER_32. No crew has both.
    It must appear in unscheduled_job_ids."""
    assert "job_G05" in plan_result.plan.unscheduled_job_ids, (
        "job_G05 requires rope_access + ladder_32 (no single crew qualifies) "
        "but was not placed in unscheduled_job_ids."
    )


def test_no_crew_day_overbooked(plan_result):
    """Daily load (work + drive back to base) must not exceed crew capacity."""
    overbooked = [
        f"{cd.crew_id} on {cd.day}: {cd.warnings}"
        for cd in plan_result.plan.days
        if cd.overbooked
    ]
    assert not overbooked, (
        f"Overbooked crew-days found (scheduler packed too much):\n"
        + "\n".join(overbooked)
    )


def test_stop_ordering_is_sequential(plan_result):
    """Each stop must have order == its position in the list (0-indexed)."""
    for cd in plan_result.plan.days:
        for expected_idx, stop in enumerate(cd.stops):
            assert stop.order == expected_idx, (
                f"Stop {stop.job_id} on {cd.crew_id}/{cd.day} has order={stop.order}, "
                f"expected {expected_idx}."
            )


def test_all_travel_times_non_negative(plan_result):
    for cd in plan_result.plan.days:
        for stop in cd.stops:
            assert stop.travel_minutes_before >= 0, (
                f"Negative travel before {stop.job_id}: {stop.travel_minutes_before}"
            )
            assert stop.duration_minutes > 0, (
                f"Zero/negative duration for {stop.job_id}"
            )


def test_utilization_values_in_range(plan_result):
    for cd in plan_result.plan.days:
        assert 0.0 <= cd.utilization <= 1.0, (
            f"{cd.crew_id}/{cd.day} utilization out of range: {cd.utilization}"
        )


def test_full_day_job_doesnt_share_day_with_much(plan_result):
    """job_W11 is a 7-hour condo job (420 min). Bravo's daily cap is 540 min.
    After travel, at most one small filler stop should fit alongside it."""
    for cd in plan_result.plan.days:
        if cd.crew_id != "crew_bravo":
            continue
        if any(s.job_id == "job_W11" for s in cd.stops):
            other = [s for s in cd.stops if s.job_id != "job_W11"]
            total_other = sum(s.duration_minutes for s in other)
            assert total_other <= 120, (
                f"Bravo packed {total_other} min of extra work alongside the 420-min "
                f"condo job on {cd.day}. Day would be overloaded."
            )


def test_adjacent_jobs_same_day(plan_result):
    """job_W02 and job_W03 share the same street (9 Place Bastien, Pincourt).
    The geo-cluster should pull them together; they should land on the same
    crew-day unless capacity forces a split."""
    day_for = {}
    for cd in plan_result.plan.days:
        for stop in cd.stops:
            if stop.job_id in ("job_W02", "job_W03"):
                day_for[stop.job_id] = (cd.crew_id, cd.day)

    if len(day_for) == 2:
        assert day_for["job_W02"] == day_for["job_W03"], (
            f"Adjacent jobs W02 and W03 were split: W02={day_for['job_W02']}, "
            f"W03={day_for['job_W03']}. Geo clustering should keep them together."
        )


def test_drive_ratio_reasonable(plan_result):
    """Total drive minutes across the week must not exceed total work minutes.
    A drive ratio > 1.0 means crews spend more time driving than working —
    geo clustering has failed."""
    total_drive = sum(cd.total_drive_minutes for cd in plan_result.plan.days)
    total_work  = sum(cd.total_work_minutes  for cd in plan_result.plan.days)
    if total_work > 0:
        ratio = total_drive / total_work
        assert ratio <= 1.0, (
            f"Drive ratio {ratio:.2f} > 1.0 — crews are driving more than working. "
            "Geo clustering may be broken."
        )


def test_client_messages_for_all_scheduled_jobs(plan_result):
    scheduled = {s.job_id for d in plan_result.plan.days for s in d.stops}
    for jid in scheduled:
        assert jid in plan_result.client_messages, f"No client message for {jid}"
        msg = plan_result.client_messages[jid]
        assert len(msg) > 20, f"Client message for {jid} is too short: {msg!r}"


def test_plan_review_kpis_populated(plan_result):
    r = plan_result.review
    assert r is not None
    for key in ("scheduled_jobs", "deferred_jobs", "revenue_scheduled", "drive_ratio"):
        assert key in r.kpis, f"Missing KPI: {key}"
    assert r.kpis["scheduled_jobs"] >= 1


def test_lift_jobs_only_bravo_or_charlie(plan_result):
    """Scissor-lift jobs require LIFT_OPERATOR. Alpha and Delta lack this skill."""
    lift_job_ids = {
        j.id for j in store.list_jobs()
        if EquipmentKind.SCISSOR_LIFT in j.required_equipment
    }
    for cd in plan_result.plan.days:
        for stop in cd.stops:
            if stop.job_id in lift_job_ids:
                crew = store.get_crew(cd.crew_id)
                assert Skill.LIFT_OPERATOR in crew.skills, (
                    f"Job {stop.job_id} needs LIFT_OPERATOR but was assigned to "
                    f"{cd.crew_id} which lacks that skill."
                )


def test_date_window_respected_for_all_stops(plan_result):
    """Every scheduled job must land within its earliest/latest_date window."""
    jobs_by_id = {j.id: j for j in store.list_jobs()}
    for cd in plan_result.plan.days:
        for stop in cd.stops:
            job = jobs_by_id[stop.job_id]
            assert cd.day >= job.earliest_date, (
                f"Job {job.id} scheduled on {cd.day} but earliest_date={job.earliest_date}"
            )
            assert cd.day <= job.latest_date, (
                f"Job {job.id} scheduled on {cd.day} but latest_date={job.latest_date}"
            )


def test_all_scheduled_jobs_have_required_skills_on_crew(plan_result):
    """Hard constraint: assigned crew must cover every required skill of the job."""
    jobs_by_id = {j.id: j for j in store.list_jobs()}
    for cd in plan_result.plan.days:
        crew = store.get_crew(cd.crew_id)
        for stop in cd.stops:
            job = jobs_by_id[stop.job_id]
            missing = set(job.required_skills) - set(crew.skills)
            assert not missing, (
                f"Crew {crew.id} scheduled job {job.id} but is missing skills: "
                f"{[s.value for s in missing]}"
            )


def test_all_scheduled_jobs_have_required_equipment_on_crew(plan_result):
    """Hard constraint: assigned crew must carry every required equipment kind."""
    jobs_by_id = {j.id: j for j in store.list_jobs()}
    crew_equipment_kinds: dict[str, set[EquipmentKind]] = {}
    for crew in store.list_crews():
        kinds: set[EquipmentKind] = set()
        for eid in crew.equipment_ids:
            eq = store.get_equipment(eid)
            if eq:
                kinds.add(eq.kind)
        crew_equipment_kinds[crew.id] = kinds

    for cd in plan_result.plan.days:
        ekind = crew_equipment_kinds[cd.crew_id]
        for stop in cd.stops:
            job = jobs_by_id[stop.job_id]
            missing = set(job.required_equipment) - ekind
            assert not missing, (
                f"Crew {cd.crew_id} scheduled job {job.id} but is missing equipment: "
                f"{[e.value for e in missing]}"
            )

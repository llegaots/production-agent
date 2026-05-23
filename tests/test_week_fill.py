"""Mon→Fri front-fill scheduling default."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.agents.supervisor import SupervisorAgent
from app.models import (
    Client,
    Crew,
    Equipment,
    EquipmentKind,
    Job,
    JobStatus,
    ServiceType,
    Skill,
)
from app.scheduling_prefs import SchedulingMode
from app.seed import BASE_LAT, BASE_LNG, SEED_WEEK_START
from app.storage import store


def _jobs_full_week(count: int = 10) -> None:
    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()

    store.clients["c1"] = Client(id="c1", name="Test", contact_phone="", contact_email="")
    store.equipment["eq_lad"] = Equipment(id="eq_lad", kind=EquipmentKind.LADDER_28, label="Ladder")
    store.equipment["eq_van"] = Equipment(id="eq_van", kind=EquipmentKind.VAN, label="Van")
    store.crews["crew_a"] = Crew(
        id="crew_a",
        name="A",
        members=["X"],
        skills=[Skill.LADDER_CERT],
        daily_minutes=8 * 60,
        base_lat=BASE_LAT,
        base_lng=BASE_LNG,
        equipment_ids=["eq_lad", "eq_van"],
    )

    week_end = SEED_WEEK_START + timedelta(days=4)
    for i in range(count):
        store.jobs[f"j{i}"] = Job(
            id=f"j{i}",
            client_id="c1",
            service_type=ServiceType.WINDOW_CLEANING,
            address=f"addr_{i}",
            lat=BASE_LAT + 0.01 * i,
            lng=BASE_LNG + 0.005 * i,
            estimated_minutes=90,
            difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.VAN],
            earliest_date=SEED_WEEK_START,
            latest_date=week_end,
            price=200.0,
            status=JobStatus.PENDING,
        )


def _stops_by_day(result) -> dict[date, int]:
    counts: dict[date, int] = {}
    for cd in result.plan.days:
        counts[cd.day] = counts.get(cd.day, 0) + len(cd.stops)
    return counts


@pytest.mark.parametrize("mode", list(SchedulingMode))
def test_plan_fills_earlier_days_before_later(mode):
    """With flexible date windows, work should land Mon→Fri before spilling late."""
    _jobs_full_week(10)
    result = asyncio.run(SupervisorAgent().plan_week(SEED_WEEK_START, scheduling_mode=mode))
    by_day = _stops_by_day(result)
    mon = by_day.get(SEED_WEEK_START, 0)
    fri = by_day.get(SEED_WEEK_START + timedelta(days=4), 0)
    assert mon >= fri, f"{mode}: Monday ({mon} stops) should fill before Friday ({fri})"

    # Cumulative front-half should carry at least as much as back-half.
    early = sum(by_day.get(SEED_WEEK_START + timedelta(days=i), 0) for i in range(3))
    late = sum(by_day.get(SEED_WEEK_START + timedelta(days=i), 0) for i in range(2, 5))
    assert early >= late, f"{mode}: early-week stops ({early}) should be >= late-week ({late})"


def test_late_only_job_respects_date_window():
    """Jobs constrained to Thu/Fri must not be pulled forward to Monday."""
    _jobs_full_week(4)
    late = SEED_WEEK_START + timedelta(days=3)
    end = SEED_WEEK_START + timedelta(days=4)
    store.jobs["late_only"] = Job(
        id="late_only",
        client_id="c1",
        service_type=ServiceType.WINDOW_CLEANING,
        address="late addr",
        lat=BASE_LAT,
        lng=BASE_LNG,
        estimated_minutes=90,
        difficulty=2,
        required_skills=[Skill.LADDER_CERT],
        required_equipment=[EquipmentKind.VAN],
        earliest_date=late,
        latest_date=end,
        price=500.0,
        status=JobStatus.PENDING,
    )
    result = asyncio.run(
        SupervisorAgent().plan_week(SEED_WEEK_START, scheduling_mode=SchedulingMode.BALANCED)
    )
    scheduled_days = {
        cd.day for cd in result.plan.days for s in cd.stops if s.job_id == "late_only"
    }
    assert scheduled_days, "late_only should be scheduled"
    assert min(scheduled_days) >= late

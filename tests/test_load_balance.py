"""Cross-crew load balancing in BALANCED scheduling mode."""
from __future__ import annotations

import asyncio
from datetime import date

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
from app.seed import SEED_WEEK_START
from app.storage import store


def _two_crew_same_skills_many_jobs():
    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()

    store.clients["cli_001"] = Client(
        id="cli_001", name="Test", contact_email="a@b.com", contact_phone="555"
    )
    store.equipment["eq_pw"] = Equipment(
        id="eq_pw", kind=EquipmentKind.PRESSURE_WASHER, label="PW", quantity=2
    )
    store.equipment["eq_van"] = Equipment(
        id="eq_van", kind=EquipmentKind.VAN, label="Van", quantity=2
    )

    for cid, base_lat in (("crew_alpha", 45.40), ("crew_delta", 45.45)):
        store.crews[cid] = Crew(
            id=cid,
            name=cid,
            members=["A"],
            skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            daily_minutes=8 * 60,
            base_lat=base_lat,
            base_lng=-73.87,
            equipment_ids=["eq_pw", "eq_van"],
        )

    tue = date(2026, 7, 7)
    for i in range(8):
        store.jobs[f"qa_job_{100 + i}"] = Job(
            id=f"qa_job_{100 + i}",
            client_id="cli_001",
            service_type=ServiceType.WINDOW_CLEANING,
            address=f"{100 + i} Main St, Kirkland QC",
            lat=45.45 + i * 0.002,
            lng=-73.87,
            estimated_minutes=90,
            difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.VAN],
            earliest_date=tue,
            latest_date=tue,
            price=200.0,
            status=JobStatus.PENDING,
        )


def _max_day_spread(result, day: date) -> int:
    loads = []
    for crew_id in ("crew_alpha", "crew_delta"):
        mins = 0
        for cd in result.plan.days:
            if cd.crew_id == crew_id and cd.day == day:
                mins = cd.total_work_minutes
        loads.append(mins)
    return max(loads) - min(loads) if loads else 0


def test_balanced_mode_reduces_same_day_crew_spread(monkeypatch):
    _two_crew_same_skills_many_jobs()
    sup = SupervisorAgent()

    monkeypatch.setattr(store, "scheduling_mode", SchedulingMode.GEO_FIRST)
    geo = asyncio.run(sup.plan_week(SEED_WEEK_START))

    _two_crew_same_skills_many_jobs()
    monkeypatch.setattr(store, "scheduling_mode", SchedulingMode.BALANCED)
    bal = asyncio.run(sup.plan_week(SEED_WEEK_START))

    tue = date(2026, 7, 7)
    geo_spread = _max_day_spread(geo, tue)
    bal_spread = _max_day_spread(bal, tue)
    assert bal_spread <= geo_spread, (
        f"BALANCED spread {bal_spread} should be <= GEO_FIRST {geo_spread} on Tuesday"
    )
    assert bal_spread <= 150, f"BALANCED Tuesday spread too wide: {bal_spread} min"
    scheduled = sum(len(cd.stops) for cd in bal.plan.days)
    assert scheduled == 8, f"Expected all 8 jobs scheduled in BALANCED mode, got {scheduled}"


def _alpha_delta_separate_equipment():
    """Two residential crews with dedicated fleet gear (seed-like)."""
    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()

    store.clients["cli_001"] = Client(
        id="cli_001", name="Test", contact_email="a@b.com", contact_phone="555"
    )
    for eid, kind, label in (
        ("eq_pw_a", EquipmentKind.PRESSURE_WASHER, "PW Alpha"),
        ("eq_pw_d", EquipmentKind.PRESSURE_WASHER, "PW Delta"),
        ("eq_lad_a", EquipmentKind.LADDER_28, "Ladder Alpha"),
        ("eq_lad_d", EquipmentKind.LADDER_28, "Ladder Delta"),
        ("eq_van_a", EquipmentKind.VAN, "Van Alpha"),
        ("eq_van_d", EquipmentKind.VAN, "Van Delta"),
    ):
        store.equipment[eid] = Equipment(id=eid, kind=kind, label=label, quantity=1)

    store.crews["crew_alpha"] = Crew(
        id="crew_alpha",
        name="Alpha",
        members=["A"],
        skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
        daily_minutes=8 * 60,
        base_lat=45.403,
        base_lng=-73.947,
        equipment_ids=["eq_pw_a", "eq_lad_a", "eq_van_a"],
    )
    store.crews["crew_delta"] = Crew(
        id="crew_delta",
        name="Delta",
        members=["B"],
        skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
        daily_minutes=8 * 60,
        base_lat=45.452,
        base_lng=-73.828,
        equipment_ids=["eq_pw_d", "eq_lad_d", "eq_van_d"],
    )

    tue = date(2026, 7, 7)
    wed = date(2026, 7, 8)
    for i, (lat, day) in enumerate(
        [(45.45, tue)] * 5 + [(45.44, tue)] * 3 + [(45.43, wed)] * 2
    ):
        store.jobs[f"job_{i}"] = Job(
            id=f"job_{i}",
            client_id="cli_001",
            service_type=ServiceType.WINDOW_CLEANING,
            address=f"{i} Oak St, Kirkland QC",
            lat=lat,
            lng=-73.87,
            estimated_minutes=90,
            difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.VAN],
            earliest_date=tue,
            latest_date=wed,
            price=200.0,
            status=JobStatus.PENDING,
        )


def test_balanced_levels_alpha_delta_tuesday(monkeypatch):
    """Replicate QA failure: Delta stacked on Tue while Alpha sits idle."""
    _alpha_delta_separate_equipment()
    monkeypatch.setattr(store, "scheduling_mode", SchedulingMode.BALANCED)
    result = asyncio.run(SupervisorAgent().plan_week(SEED_WEEK_START))

    tue = date(2026, 7, 7)
    spread = _max_day_spread(result, tue)
    assert spread <= 150, f"Tuesday Alpha/Delta spread {spread} min exceeds 150 min cap"

    loads = {}
    for crew_id in ("crew_alpha", "crew_delta"):
        for cd in result.plan.days:
            if cd.crew_id == crew_id and cd.day == tue:
                loads[crew_id] = cd.total_work_minutes
    if loads:
        assert max(loads.values()) - min(loads.values()) <= 150
    scheduled = sum(len(cd.stops) for cd in result.plan.days)
    assert scheduled == 10, f"Expected all 10 jobs scheduled, got {scheduled}"

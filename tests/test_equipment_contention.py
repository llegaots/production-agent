"""Regression: exclusive equipment (scissor-lift) cannot double-book on one crew-day."""
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
from app.seed import SEED_WEEK_START
from app.storage import store


def _minimal_store_two_lift_jobs_same_day():
    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()

    store.clients["cli_001"] = Client(
        id="cli_001",
        name="Test",
        contact_email="a@b.com",
        contact_phone="555",
    )
    store.equipment["eq_lift"] = Equipment(
        id="eq_lift", kind=EquipmentKind.SCISSOR_LIFT, label="Lift", quantity=1
    )
    store.equipment["eq_van"] = Equipment(
        id="eq_van", kind=EquipmentKind.VAN, label="Van", quantity=1
    )
    store.crews["crew_bravo"] = Crew(
        id="crew_bravo",
        name="Bravo",
        members=["Bob"],
        skills=[Skill.LADDER_CERT, Skill.LIFT_OPERATOR],
        daily_minutes=8 * 60,
        base_lat=45.45,
        base_lng=-73.87,
        equipment_ids=["eq_lift", "eq_van"],
    )

    wed = date(2026, 7, 8)
    for jid, addr, price in (
        ("qa_job_024", "100 Av. Fairview, Pointe-Claire QC", 800.0),
        ("qa_job_025", "200 Bd Beaconsfield, Beaconsfield QC", 750.0),
    ):
        store.jobs[jid] = Job(
            id=jid,
            client_id="cli_001",
            service_type=ServiceType.GUTTER_CLEANING,
            address=addr,
            lat=45.45 + (0.001 if jid.endswith("5") else 0.0),
            lng=-73.87,
            estimated_minutes=180,
            difficulty=3,
            required_skills=[Skill.LADDER_CERT, Skill.LIFT_OPERATOR],
            required_equipment=[EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN],
            earliest_date=wed,
            latest_date=wed,
            price=price,
            status=JobStatus.PENDING,
        )


def test_scissor_lift_double_book_deferred():
    _minimal_store_two_lift_jobs_same_day()
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week(SEED_WEEK_START))

    wed = date(2026, 7, 8)
    bravo_wed_stops = [
        s.job_id
        for cd in result.plan.days
        if cd.crew_id == "crew_bravo" and cd.day == wed
        for s in cd.stops
    ]
    lift_on_day = [jid for jid in bravo_wed_stops if jid in ("qa_job_024", "qa_job_025")]
    assert len(lift_on_day) == 1, (
        f"Expected exactly one scissor-lift job on Bravo Wednesday, got {lift_on_day}"
    )
    unsched = set(result.plan.unscheduled_job_ids)
    assert "qa_job_024" in unsched or "qa_job_025" in unsched, (
        f"One lift job must be unscheduled, stops={lift_on_day} unsched={unsched}"
    )

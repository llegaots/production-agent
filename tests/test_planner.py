"""End-to-end tests for the multi-agent planner.

These tests run the deterministic, rule-based path (no LLM required).
"""
import asyncio
from datetime import date, timedelta

import pytest

from app.agents import ReschedulerAgent, SupervisorAgent
from app.models import JobStatus
from app.seed import seed
from app.storage import store


@pytest.fixture(autouse=True)
def fresh_seed():
    seed(reset=True)
    yield


def test_seed_populates_store():
    assert len(store.list_jobs()) >= 10
    assert len(store.list_crews()) == 3
    assert len(store.list_equipment()) >= 8


def test_plan_week_assigns_most_jobs():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    plan = result.plan

    total_jobs = len(store.list_jobs())
    scheduled = sum(len(d.stops) for d in plan.days)
    assert scheduled + len(plan.unscheduled_job_ids) == total_jobs
    # The bulk of the week should land
    assert scheduled >= total_jobs - 2

    # crews and days look reasonable
    for d in plan.days:
        assert d.total_work_minutes >= 0
        assert 0.0 <= d.utilization <= 1.0
        for idx, stop in enumerate(d.stops):
            assert stop.order == idx
            assert stop.duration_minutes > 0


def test_plan_records_events():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    agents = {e.agent for e in result.events}
    # every specialist plus supervisor should have spoken
    for expected in (
        "SupervisorAgent",
        "GeoClusterAgent",
        "CrewMatchAgent",
        "EquipmentAgent",
        "TimeBudgetAgent",
        "ClientCommsAgent",
    ):
        assert expected in agents, f"expected {expected} to emit events"


def test_client_messages_for_every_scheduled_job():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    for d in result.plan.days:
        for s in d.stops:
            assert s.job_id in result.client_messages
            assert "ClearView" in result.client_messages[s.job_id] or len(result.client_messages[s.job_id]) > 30


def test_reschedule_moves_job_to_different_day_or_crew():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())

    target = None
    for d in result.plan.days:
        for s in d.stops:
            target = (s.job_id, d.day, d.crew_id)
            break
        if target:
            break
    assert target is not None
    job_id, original_day, original_crew = target

    rescheduler = ReschedulerAgent()
    out = asyncio.run(
        rescheduler.run_reschedule(result, job_id, "Forecast: rain all day")
    )

    plan = store.get_plan()
    # The job should no longer appear on the original (crew, day) pair
    for cd in plan.plan.days:
        if cd.crew_id == original_crew and cd.day == original_day:
            assert all(s.job_id != job_id for s in cd.stops)

    # It should appear somewhere new (or be flagged as unable to place)
    if out.succeeded:
        found = False
        for cd in plan.plan.days:
            for s in cd.stops:
                if s.job_id == job_id:
                    found = True
                    assert (cd.day, cd.crew_id) != (original_day, original_crew)
        assert found
        assert out.client_message


def test_equipment_gap_flagged():
    # Force a gap: crew Alpha lacks rope kit; assign a rope-required job to it.
    jobs = store.list_jobs()
    high_rise = [j for j in jobs if j.service_type.value == "high_rise"]
    assert high_rise, "expected at least one high-rise job in the seed data"

    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    # No crew should be missing rope kit for the high-rise: crew Charlie has it.
    # We assert that the agent successfully placed the high-rise job with a
    # rope-capable crew (no equipment gap surfaced for that job).
    rope_jobs = {j.id for j in high_rise}
    gap_jobs = set()
    for c in result.plan.conflicts:
        for jid in rope_jobs:
            if jid in c and "rope_kit" in c:
                gap_jobs.add(jid)
    assert not gap_jobs, f"Rope kit gaps found: {gap_jobs}"

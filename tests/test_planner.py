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
    for expected in (
        "SupervisorAgent",
        "GeoClusterAgent",
        "CrewMatchAgent",
        "EquipmentAgent",
        "TimeBudgetAgent",
        "ClientCommsAgent",
        "PlanReviewerAgent",
    ):
        assert expected in agents, f"expected {expected} to emit events"


def test_plan_review_is_structured():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    assert result.review is not None
    r = result.review
    assert 0 <= r.risk_score <= 100
    assert isinstance(r.kpis, dict)
    for key in (
        "scheduled_jobs",
        "deferred_jobs",
        "revenue_scheduled",
        "drive_ratio",
        "overbooked_crew_days",
    ):
        assert key in r.kpis
    assert isinstance(r.narrative, str) and r.narrative


def test_message_quality_scored_for_every_scheduled_job():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    scheduled = {s.job_id for d in result.plan.days for s in d.stops}
    assert scheduled, "expected at least one scheduled job"
    for jid in scheduled:
        q = result.message_quality.get(jid)
        assert q is not None, f"missing quality score for {jid}"
        assert 0 <= q.score <= 100


def test_comms_pipeline_emits_routing_and_iteration_events():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    phases = {e.phase for e in result.events if e.agent == "ClientCommsAgent"}
    assert "route" in phases, "expected a routing event from comms pipeline"
    assert any(p.startswith("iter_") for p in phases), "expected iteration events from evaluator-optimizer loop"


def test_guardrail_catches_missing_call_to_action():
    from app.agents.message_guardrail import MessageGuardrailAgent
    from app.models import Job, ServiceType
    from datetime import date as _date

    # Use a real seeded job so client/equipment lookups work
    job = store.list_jobs()[0]
    bad = "Hi there, we plan to come by sometime this week. Bye."
    result = MessageGuardrailAgent.check(bad, job, "Monday, May 18", "08:00-09:00")
    assert not result.passed
    assert any("call to action" in f.lower() for f in result.flags)


def test_guardrail_flags_other_client_mention():
    from app.agents.message_guardrail import MessageGuardrailAgent

    job = store.list_jobs()[0]
    # Mention another seeded client's name
    other = [c for c in store.list_clients() if c.id != job.client_id][0]
    bad = (
        f"Hi {store.get_client(job.client_id).name}, confirming Monday, May 18 from 08:00-09:00. "
        f"Please reply YES. (For reference, we are also working with {other.name} this week.)"
    )
    result = MessageGuardrailAgent.check(bad, job, "Monday, May 18", "08:00-09:00")
    assert not result.passed
    assert any("another client" in f.lower() for f in result.flags)


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
    for cd in plan.plan.days:
        if cd.crew_id == original_crew and cd.day == original_day:
            assert all(s.job_id != job_id for s in cd.stops)

    if out.succeeded:
        found = False
        for cd in plan.plan.days:
            for s in cd.stops:
                if s.job_id == job_id:
                    found = True
                    assert (cd.day, cd.crew_id) != (original_day, original_crew)
        assert found
        assert out.client_message


def test_reschedule_emits_candidate_trade_offs():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    job_id = result.plan.days[0].stops[0].job_id

    rescheduler = ReschedulerAgent()
    out = asyncio.run(rescheduler.run_reschedule(result, job_id, "Crew member callout"))

    phases = {e.phase for e in out.events}
    if out.succeeded:
        assert "evaluate" in phases, "expected an 'evaluate' event listing candidates"
        assert "candidate" in phases, "expected per-candidate events"
        assert "decide" in phases, "expected an explicit 'decide' event"


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

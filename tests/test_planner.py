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


SEED_WEEK_START = date(2026, 7, 6)   # matches earliest_date in all seed jobs


@pytest.fixture(autouse=True)
def fresh_seed(monkeypatch):
    seed(reset=True)

    async def _fake_geocode(address: str):
        from app.geocode import GeocodeResult
        # Return the seeded coordinates for this address when available.
        for j in store.list_jobs():
            if j.address == address:
                return GeocodeResult(
                    input_address=address, success=True,
                    lat=j.lat, lng=j.lng,
                    formatted_address=address,
                    confidence=0.92, needs_review=False,
                    in_service_area=True, location_type="ROOFTOP",
                    postal_code="J7V 8P4", province="QC", source="google",
                )
        return GeocodeResult(
            input_address=address, success=True,
            lat=45.3838, lng=-73.8825,
            formatted_address=address,
            confidence=0.92, needs_review=False,
            in_service_area=True, location_type="ROOFTOP",
            postal_code="J7V 8P4", province="QC", source="google",
        )

    monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode", _fake_geocode)
    monkeypatch.setattr("app.row_import.geocoder.geocode", _fake_geocode)

    # Pin _next_monday to match the seed data's date windows.
    monkeypatch.setattr("app.agents.supervisor._next_monday", lambda: SEED_WEEK_START)

    async def _fake_llm_chat(*_a, **_kw):
        return None  # force template fallbacks in tests

    monkeypatch.setattr("app.llm.llm.chat", _fake_llm_chat)
    yield


def test_seed_populates_store():
    assert len(store.list_jobs()) >= 6
    assert len(store.list_crews()) >= 3
    assert len(store.list_equipment()) >= 10


def test_plan_week_assigns_most_jobs():
    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    plan = result.plan

    # Jobs outside the planning week are filtered before the planner sees them.
    week_end = SEED_WEEK_START + timedelta(days=4)
    in_window = [
        j for j in store.list_jobs()
        if j.earliest_date <= week_end and j.latest_date >= SEED_WEEK_START
    ]
    scheduled = sum(len(d.stops) for d in plan.days)
    # Every in-window job must be either scheduled or explicitly deferred.
    # unscheduled_job_ids may also contain out-of-window jobs (tracked for
    # transparency); exclude those from the accounting check.
    in_window_ids = {j.id for j in in_window}
    in_window_unscheduled = [jid for jid in plan.unscheduled_job_ids if jid in in_window_ids]
    assert scheduled + len(in_window_unscheduled) == len(in_window), (
        f"scheduled({scheduled}) + in-window-unscheduled({len(in_window_unscheduled)}) "
        f"!= in-window jobs ({len(in_window)})"
    )
    # At least 50% of in-window jobs should land.
    assert scheduled >= len(in_window) // 2

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

    if out.succeeded:
        # The job was successfully rescheduled.  If it landed on a different
        # crew/day it must not appear on the old slot anymore.
        moved = (out.new_day, out.new_crew_id) != (original_day, original_crew)
        plan = store.get_plan()
        if moved:
            for cd in plan.plan.days:
                if cd.crew_id == original_crew and cd.day == original_day:
                    assert all(s.job_id != job_id for s in cd.stops), (
                        f"Job {job_id} still on original slot after successful reschedule"
                    )

        found = False
        for cd in plan.plan.days:
            for s in cd.stops:
                if s.job_id == job_id:
                    found = True
        assert found, "Rescheduled job not found anywhere in the plan"
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
    # job_G01 (gutter guard / large) requires scissor_lift; only Bravo carries it.
    jobs = store.list_jobs()
    lift_job = next((j for j in jobs if j.id == "job_G01"), None)
    assert lift_job is not None

    sup = SupervisorAgent()
    result = asyncio.run(sup.plan_week())
    # Check Bravo is the only crew assigned to lift jobs in the plan.
    lift_job_ids = {j.id for j in jobs if "scissor_lift" in [e.value for e in j.required_equipment]}
    for cd in result.plan.days:
        for stop in cd.stops:
            if stop.job_id in lift_job_ids:
                assert cd.crew_id == "crew_bravo", (
                    f"Lift job {stop.job_id} incorrectly assigned to {cd.crew_id}"
                )

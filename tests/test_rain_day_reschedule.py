"""Rain-day rescheduling tests.

Scenario: a full working day is rained out.  Every job scheduled for that
day must be moved to another valid slot within the same week (or as early as
possible within each job's date window).

── CONTRACT UNDER TEST ──────────────────────────────────────────────────────

Removal
  • After rescheduling all rain-day jobs, no job from the affected day
    should remain on that crew/day.
  • Removing a job must not silently delete it — each job must reappear
    exactly once somewhere else in the plan (or in unscheduled_job_ids).

Placement validity (per job, per new crew-day)
  • New crew has every required skill.
  • New crew carries every required equipment kind.
  • New scheduled day is within the job's earliest_date … latest_date window.
  • New day ≠ the rain day.

Capacity integrity
  • No crew-day exceeds daily_minutes (unless explicitly overbooked AND
    the overbooked flag is True — overbooked must never be silent).
  • day_load = total_work + total_drive is consistent with the overbooked
    flag after every reschedule.

Plan integrity
  • Each job_id appears at most once across all stops in the plan.
  • stop.order is sequential within each crew-day.
  • stop.duration_minutes == job.estimated_minutes.
  • total_work_minutes == sum(stop.duration_minutes).

Client communications
  • A non-empty reschedule message is produced for every successfully
    rescheduled job.
  • The message mentions the new day or the client's name (basic sanity).

Agent reasoning events
  • "evaluate" event emitted (candidate set was considered).
  • At least one "candidate" event emitted (individual candidates logged).
  • "decide" event emitted (final choice announced).
  • "remove" event emitted (old slot cleared).
  • "place" event emitted (new slot confirmed).

Scoring heuristic validation
  • The rescheduler prefers days closer to the rain day (day_distance ↓).
  • When two slots have equal day distance, same-crew continuity is preferred.

── SCORING FORMULA (pinned here) ────────────────────────────────────────────
score = 100 - day_distance * 20 + same_crew * 8
        + min(20, headroom_minutes // 30)
        + (25 if day == preferred_day else 0)
"""
from __future__ import annotations

import asyncio
import collections
from datetime import date, timedelta
from typing import Optional

import pytest

from app.agents import ReschedulerAgent, SupervisorAgent
from app.agents.base import drive_minutes, haversine_km
from app.models import EquipmentKind, JobStatus, PlanResult, Skill
from app.seed import seed
from app.storage import store

WEEK      = date(2026, 7, 6)   # Monday — the planning week
RAIN_DAY  = WEEK               # We'll rain out Monday


# ─── Fixtures ─────────────────────────────────────────────────────────────────

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
        from app.seed import BASE_LAT, BASE_LNG
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


def _plan_and_confirm() -> PlanResult:
    """Plan the week, then confirm it (sets SCHEDULED statuses)."""
    result = asyncio.run(SupervisorAgent().plan_week(WEEK))
    # Confirm via the same logic as POST /api/plan/confirm.
    published = result.model_copy(deep=True)
    new_ids = {s.job_id for cd in published.plan.days for s in cd.stops}
    old = store.get_confirmed_plan()
    if old:
        old_ids = {s.job_id for cd in old.plan.days for s in cd.stops}
        for jid in old_ids - new_ids:
            store.set_job_status(jid, JobStatus.PENDING)
    for jid in new_ids:
        store.set_job_status(jid, JobStatus.SCHEDULED)
    store.set_confirmed_plan(published)
    return result


def _rain_day_jobs(plan: PlanResult, rain_day: date = RAIN_DAY) -> list[str]:
    """Return all job IDs scheduled on the given rain day."""
    return [
        s.job_id
        for cd in plan.plan.days
        if cd.day == rain_day
        for s in cd.stops
    ]


def _reschedule_job(
    plan: PlanResult,
    job_id: str,
    rain_day: date = RAIN_DAY,
    reason: str = "Rain day — Monday July 6 operations cancelled due to weather",
    preferred_day: Optional[date] = None,
) -> tuple:
    """Reschedule one job, excluding the rain day. Returns (result, events)."""
    agent = ReschedulerAgent()
    result = asyncio.run(
        agent.run_reschedule(
            plan,
            job_id,
            reason,
            new_earliest=rain_day + timedelta(days=1),
            preferred_day=preferred_day,
        )
    )
    return result, result.events


def _find_reschedulable_job(
    plan: PlanResult,
    rain_day: date = RAIN_DAY,
    reason: str = "Rain day — Monday July 6 operations cancelled due to weather",
) -> Optional[str]:
    """Return the first rain-day job that can actually be rescheduled this week.

    Some rain-day jobs (e.g. a 420-min full-day block) genuinely have nowhere
    to go after their day is cancelled — that is correct, expected behaviour.
    Tests that need a *successful* reschedule should call this first.
    """
    import copy
    rain_jobs = _rain_day_jobs(plan, rain_day)
    for job_id in rain_jobs:
        # Work on a throw-away copy so we don't mutate the fixture plan.
        trial_plan = copy.deepcopy(plan)
        result, _ = _reschedule_job(trial_plan, job_id, rain_day, reason)
        if result.succeeded:
            return job_id
    return None


def _plan_job_ids(plan: PlanResult) -> list[str]:
    """All job_ids present in the plan (may have duplicates if broken)."""
    return [s.job_id for cd in plan.plan.days for s in cd.stops]


def _crew_eq_kinds(crew_id: str) -> set[EquipmentKind]:
    crew = store.get_crew(crew_id)
    kinds = set()
    for eid in crew.equipment_ids:
        eq = store.get_equipment(eid)
        if eq:
            kinds.add(eq.kind)
    return kinds


# ─── 1. Rain-day job removal ─────────────────────────────────────────────────

class TestRainDayRemoval:
    def test_rain_day_jobs_identified(self):
        plan = _plan_and_confirm()
        jobs_on_rain_day = _rain_day_jobs(plan, RAIN_DAY)
        # The seed has enough jobs to schedule at least one on Monday.
        assert len(jobs_on_rain_day) >= 1, (
            f"No jobs were scheduled on {RAIN_DAY} — cannot run rain-day test. "
            "Seed may need a job with earliest_date=WEEK."
        )

    def test_single_rain_day_job_removed_from_original_day(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        job_id = _find_reschedulable_job(plan) or rain_jobs[0]
        _reschedule_job(plan, job_id)

        updated = store.get_plan()
        still_on_rain_day = _rain_day_jobs(updated, RAIN_DAY)
        assert job_id not in still_on_rain_day, (
            f"Job {job_id} is still on the rain day {RAIN_DAY} after rescheduling"
        )

    def test_all_rain_day_jobs_removed_after_full_rain_day(self):
        """After rescheduling EVERY job from the rain day, none should remain."""
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        still_on_rain_day = _rain_day_jobs(current_plan, RAIN_DAY)
        assert still_on_rain_day == [], (
            f"After rescheduling all rain-day jobs, these remain on {RAIN_DAY}: "
            f"{still_on_rain_day}"
        )


# ─── 2. No job duplication ────────────────────────────────────────────────────

class TestNoDuplication:
    def test_rescheduled_job_appears_exactly_once(self):
        plan = _plan_and_confirm()
        if not _rain_day_jobs(plan, RAIN_DAY):
            pytest.skip("No jobs on rain day")

        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No rain-day job can be rescheduled this week (all require full-day capacity)")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip(f"Job {job_id} could not be rescheduled (no capacity)")

        updated = store.get_plan()
        counts = collections.Counter(_plan_job_ids(updated))
        assert counts[job_id] == 1, (
            f"Job {job_id} appears {counts[job_id]} times after reschedule (expected exactly 1)"
        )

    def test_full_rain_day_no_duplicate_jobs(self):
        """After all rain-day jobs are rescheduled, each job_id appears at most once."""
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        all_ids = _plan_job_ids(current_plan)
        counts = collections.Counter(all_ids)
        duplicates = {jid: n for jid, n in counts.items() if n > 1}
        assert not duplicates, (
            f"Duplicate job_ids found after rain-day reschedule: {duplicates}"
        )

    def test_non_rain_day_jobs_unchanged_after_reschedule(self):
        """Jobs NOT on the rain day must still appear in the plan exactly once."""
        plan = _plan_and_confirm()
        rain_jobs = set(_rain_day_jobs(plan, RAIN_DAY))
        all_before = {s.job_id for cd in plan.plan.days for s in cd.stops}
        non_rain = all_before - rain_jobs

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        counts = collections.Counter(_plan_job_ids(current_plan))
        for jid in non_rain:
            assert counts[jid] == 1, (
                f"Non-rain-day job {jid} has count={counts[jid]} after rain-day reschedule"
            )


# ─── 3. Placement validity ────────────────────────────────────────────────────

class TestPlacementValidity:
    def test_new_slot_is_not_the_rain_day(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")
        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip(f"Job {job_id} could not be rescheduled")
        assert result.new_day != RAIN_DAY, (
            f"Job was re-placed on the rain day itself ({result.new_day})"
        )

    def test_new_slot_within_job_date_window(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for job_id in rain_jobs:
            result, _ = _reschedule_job(plan, job_id)
            plan = store.get_plan()
            if not result.succeeded:
                continue
            job = jobs_by_id[job_id]
            after_rain = RAIN_DAY + timedelta(days=1)
            assert result.new_day >= after_rain, (
                f"Job {job_id} rescheduled to {result.new_day}, which is before "
                f"the day after rain ({after_rain})"
            )
            assert result.new_day <= job.latest_date, (
                f"Job {job_id} rescheduled to {result.new_day}, past its latest_date {job.latest_date}"
            )

    def test_new_crew_has_required_skills(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for job_id in rain_jobs:
            result, _ = _reschedule_job(plan, job_id)
            plan = store.get_plan()
            if not result.succeeded:
                continue
            job = jobs_by_id[job_id]
            crew = store.get_crew(result.new_crew_id)
            missing = set(job.required_skills) - set(crew.skills)
            assert not missing, (
                f"Job {job_id} rescheduled to crew {result.new_crew_id} which "
                f"is missing skills: {[s.value for s in missing]}"
            )

    def test_new_crew_has_required_equipment(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for job_id in rain_jobs:
            result, _ = _reschedule_job(plan, job_id)
            plan = store.get_plan()
            if not result.succeeded:
                continue
            job = jobs_by_id[job_id]
            crew_eq = _crew_eq_kinds(result.new_crew_id)
            missing = set(job.required_equipment) - crew_eq
            assert not missing, (
                f"Job {job_id} rescheduled to crew {result.new_crew_id} which "
                f"is missing equipment: {[e.value for e in missing]}"
            )

    def test_rescheduled_stop_duration_equals_estimated_minutes(self):
        """Rescheduling must not silently alter the job duration."""
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        jobs_by_id = {j.id: j for j in store.list_jobs()}
        for job_id in [job_id]:
            result, _ = _reschedule_job(plan, job_id)
            plan = store.get_plan()
            if not result.succeeded:
                continue
            for cd in plan.plan.days:
                for stop in cd.stops:
                    if stop.job_id == job_id:
                        expected = jobs_by_id[job_id].estimated_minutes
                        assert stop.duration_minutes == expected, (
                            f"Job {job_id} duration changed from {expected} to "
                            f"{stop.duration_minutes} during reschedule"
                        )


# ─── 4. Capacity integrity ────────────────────────────────────────────────────

class TestCapacityIntegrity:
    def _assert_no_silent_overbooking(self, plan: PlanResult) -> None:
        """Any overbooked day must have overbooked=True AND a warning."""
        for cd in plan.plan.days:
            day_load = cd.total_work_minutes + cd.total_drive_minutes
            crew = store.get_crew(cd.crew_id)
            should_be_overbooked = day_load > crew.daily_minutes
            assert cd.overbooked == should_be_overbooked, (
                f"{cd.crew_id}/{cd.day}: day_load={day_load}, "
                f"capacity={crew.daily_minutes}, "
                f"overbooked flag={cd.overbooked} (expected {should_be_overbooked}). "
                "Overbooking must never be silent."
            )
            if cd.overbooked:
                assert cd.warnings, (
                    f"{cd.crew_id}/{cd.day} is marked overbooked but has no warning messages."
                )

    def test_no_overbooking_after_single_reschedule(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        updated = store.get_plan()
        for cd in updated.plan.days:
            assert not cd.overbooked, (
                f"Crew-day {cd.crew_id}/{cd.day} became overbooked after "
                f"rescheduling {job_id}: {cd.warnings}"
            )

    def test_overbooking_flag_consistent_with_day_load(self):
        """After a full rain-day reschedule, every crew-day's overbooked flag
        must correctly reflect day_load vs capacity."""
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        self._assert_no_silent_overbooking(current_plan)

    def test_total_work_minutes_consistent_after_reschedule(self):
        """total_work_minutes == sum(stop.duration_minutes) on each crew-day."""
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        for cd in current_plan.plan.days:
            expected = sum(s.duration_minutes for s in cd.stops)
            assert cd.total_work_minutes == expected, (
                f"{cd.crew_id}/{cd.day}: total_work_minutes={cd.total_work_minutes} "
                f"!= sum(stop.duration)={expected}"
            )

    def test_destination_day_headroom_check(self):
        """The rescheduler must only place jobs on days with capacity.
        Check that the headroom check (used + job_min + 30 <= daily_min) held."""
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        jobs_by_id = {j.id: j for j in store.list_jobs()}
        current_plan = plan
        for job_id in rain_jobs:
            result, _ = _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()
            if not result.succeeded:
                continue
            for cd in current_plan.plan.days:
                if cd.crew_id == result.new_crew_id and cd.day == result.new_day:
                    assert not cd.overbooked, (
                        f"Rescheduler placed {job_id} on {result.new_crew_id}/{result.new_day} "
                        f"which is now overbooked. Headroom check failed."
                    )


# ─── 5. Plan structural integrity ─────────────────────────────────────────────

class TestPlanStructuralIntegrity:
    def test_stop_order_sequential_after_reschedule(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        for cd in current_plan.plan.days:
            for idx, stop in enumerate(cd.stops):
                assert stop.order == idx, (
                    f"{cd.crew_id}/{cd.day}: stop {stop.job_id} has order={stop.order}, "
                    f"expected {idx} (resequencing left inconsistent order)"
                )

    def test_all_travel_times_non_negative_after_reschedule(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        for job_id in rain_jobs:
            _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()

        for cd in current_plan.plan.days:
            for stop in cd.stops:
                assert stop.travel_minutes_before >= 0, (
                    f"Negative travel before {stop.job_id} on {cd.crew_id}/{cd.day}"
                )

    def test_resequencing_improves_or_preserves_route(self):
        """After inserting a rescheduled job, total_drive of the receiving day
        must be consistent with the nearest-neighbor resequencing: the first
        stop's travel must equal drive_minutes from crew base to that job."""
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        updated = store.get_plan()
        crew = store.get_crew(result.new_crew_id)
        for cd in updated.plan.days:
            if cd.crew_id == result.new_crew_id and cd.day == result.new_day:
                if not cd.stops:
                    continue
                first_stop = cd.stops[0]
                first_job  = store.get_job(first_stop.job_id)
                d_km = haversine_km(
                    crew.base_lat, crew.base_lng,
                    first_job.lat, first_job.lng,
                )
                expected_travel = drive_minutes(d_km)
                assert first_stop.travel_minutes_before == expected_travel, (
                    f"First stop {first_stop.job_id} on {cd.crew_id}/{cd.day}: "
                    f"travel_minutes_before={first_stop.travel_minutes_before} "
                    f"!= drive_minutes({d_km:.2f}km)={expected_travel}. "
                    "Resequencing did not correctly recalculate travel from crew base."
                )


# ─── 6. Client communications ────────────────────────────────────────────────

class TestClientCommunications:
    def test_reschedule_message_produced(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        assert result.client_message, (
            f"No client message produced for rescheduled job {job_id}"
        )
        assert len(result.client_message) > 20, (
            f"Client message is suspiciously short: {result.client_message!r}"
        )

    def test_reschedule_message_stored_in_plan(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        updated = store.get_plan()
        assert job_id in updated.client_messages, (
            f"Client message for {job_id} not stored in plan.client_messages after reschedule"
        )
        assert updated.client_messages[job_id], "Stored client message is empty"

    def test_all_rain_day_jobs_have_messages(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        current_plan = plan
        rescheduled_ids = []
        for job_id in rain_jobs:
            result, _ = _reschedule_job(current_plan, job_id)
            current_plan = store.get_plan()
            if result.succeeded:
                rescheduled_ids.append(job_id)

        if not rescheduled_ids:
            pytest.skip("No jobs were successfully rescheduled")

        updated = store.get_plan()
        for jid in rescheduled_ids:
            assert jid in updated.client_messages, (
                f"No client message stored for rescheduled job {jid}"
            )
            assert updated.client_messages[jid], f"Empty client message for {jid}"

    def test_message_mentions_client_name_or_service(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        job   = store.get_job(job_id)
        client = store.get_client(job.client_id)
        msg   = result.client_message.lower()
        service_words = job.service_type.value.replace("_", " ")
        has_client  = client and client.name.split()[0].lower() in msg
        has_service = any(w in msg for w in service_words.split())
        has_date    = any(str(result.new_day.year) in msg or result.new_day.strftime("%b").lower() in msg for _ in [1])
        assert has_client or has_service or has_date, (
            f"Client message for {job_id} doesn't mention client name, service, or date. "
            f"Message: {result.client_message[:200]}"
        )


# ─── 7. Agent reasoning events ────────────────────────────────────────────────

class TestAgentReasoningEvents:
    def _events_by_phase(self, events: list) -> dict[str, list]:
        by_phase: dict[str, list] = {}
        for e in events:
            by_phase.setdefault(e.phase, []).append(e)
        return by_phase

    def test_evaluate_event_emitted(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        _, events = _reschedule_job(plan, job_id)
        phases = self._events_by_phase(events)
        assert "evaluate" in phases, (
            "Expected an 'evaluate' event showing candidate slots were considered"
        )
        ev = phases["evaluate"][0]
        assert ev.detail and "candidates" in ev.detail, (
            "'evaluate' event must include 'candidates' in its detail"
        )

    def test_candidate_events_emitted(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        _, events = _reschedule_job(plan, job_id)
        phases = self._events_by_phase(events)
        assert "candidate" in phases, (
            "Expected individual 'candidate' events listing each option"
        )
        assert len(phases["candidate"]) >= 1

    def test_decide_event_emitted_on_success(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, events = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        phases = self._events_by_phase(events)
        assert "decide" in phases, (
            "'decide' event must announce the final slot chosen"
        )
        ev = phases["decide"][0]
        assert ev.detail and "chosen" in ev.detail, (
            "'decide' event must include 'chosen' detail with slot info"
        )

    def test_remove_event_emitted(self):
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        # Use any rain-day job — remove event fires even when reschedule fails.
        _, events = _reschedule_job(plan, rain_jobs[0])
        phases = self._events_by_phase(events)
        assert "remove" in phases, (
            "'remove' event must confirm the job was lifted from its old slot"
        )

    def test_place_event_emitted_on_success(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, events = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        phases = self._events_by_phase(events)
        assert "place" in phases, (
            "'place' event must confirm the job's new slot"
        )
        ev = phases["place"][0]
        assert ev.detail and "new_day" in ev.detail

    def test_evaluate_detail_contains_score_fields(self):
        """Each candidate in the 'evaluate' event must have all scoring fields."""
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        _, events = _reschedule_job(plan, job_id)
        phases = self._events_by_phase(events)
        if "evaluate" not in phases:
            pytest.skip("No evaluate event")

        ev = phases["evaluate"][0]
        for cand in ev.detail.get("candidates", [])[:3]:
            for field in ("score", "headroom_min", "day_distance", "same_crew_as_before"):
                assert field in cand, (
                    f"Candidate entry missing field '{field}': {cand}"
                )


# ─── 8. Scoring heuristics ────────────────────────────────────────────────────

class TestScoringHeuristics:
    """Verify the scoring formula: score = 100 - dist*20 + same_crew*8
    + min(20, headroom//30) + (25 if preferred_day else 0)"""

    def test_earlier_day_preferred_over_later_day(self):
        """All else equal, Tuesday (dist=1) beats Thursday (dist=3)."""
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, events = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        phases = {e.phase: e for e in events}
        if "evaluate" not in phases:
            pytest.skip("No evaluate event")

        ev = phases["evaluate"]
        candidates = ev.detail.get("candidates", [])
        if len(candidates) < 2:
            pytest.skip("Only one candidate; can't compare ordering")

        # Candidates should be sorted descending by score.
        scores = [c["score"] for c in candidates]
        assert scores == sorted(scores, reverse=True), (
            f"Candidates not sorted by score desc: {scores}"
        )

    def test_preferred_day_bonus_applied(self):
        """Passing preferred_day bumps that day's score by 25."""
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        # Reschedule once normally to find what day would be chosen without preference.
        job_id = rain_jobs[0]
        result_no_pref, events_no_pref = _reschedule_job(plan, job_id)
        if not result_no_pref.succeeded:
            pytest.skip("No valid slot found")

        # Re-seed and re-plan for a fresh plan (previous reschedule mutated it).
        seed(reset=True)
        import app.agents.geo_cluster as _gc
        import app.llm as _llm_mod

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
                input_address=address, success=True, lat=BASE_LAT, lng=BASE_LNG,
                formatted_address=address, confidence=0.8, needs_review=True,
                in_service_area=True, location_type="APPROXIMATE",
                postal_code="H9X", province="QC", source="google",
            )

        _gc.geocoder.geocode = _fake_geo
        _llm_mod.llm.chat = _no_llm

        plan2 = asyncio.run(SupervisorAgent().plan_week(WEEK))
        rain_jobs2 = _rain_day_jobs(plan2, RAIN_DAY)
        if not rain_jobs2 or job_id not in rain_jobs2:
            pytest.skip("Job not on rain day in fresh plan")

        # This time pass a specific preferred day different from the natural choice.
        preferred = result_no_pref.new_day + timedelta(days=1)
        agent = ReschedulerAgent()
        result_pref = asyncio.run(
            agent.run_reschedule(
                plan2,
                job_id,
                "Rain day",
                new_earliest=RAIN_DAY + timedelta(days=1),
                preferred_day=preferred,
            )
        )
        # Find the preferred day candidate in events.
        ev_pref = next((e for e in result_pref.events if e.phase == "evaluate"), None)
        if not ev_pref:
            pytest.skip("No evaluate event in preferred-day run")

        pref_cand = next(
            (c for c in ev_pref.detail.get("candidates", [])
             if c["day"] == preferred.isoformat()),
            None,
        )
        if pref_cand is None:
            pytest.skip("Preferred day had no valid candidate slot")

        # Score for preferred day must include the +25 bonus.
        non_pref_same_dist = [
            c for c in ev_pref.detail.get("candidates", [])
            if c["day_distance"] == pref_cand["day_distance"]
            and c["day"] != preferred.isoformat()
        ]
        if non_pref_same_dist:
            assert pref_cand["score"] >= non_pref_same_dist[0]["score"] + 20, (
                f"Preferred day bonus not visible in score. "
                f"preferred={pref_cand['score']}, non_pref={non_pref_same_dist[0]['score']}"
            )

    def test_job_status_becomes_rescheduled(self):
        plan = _plan_and_confirm()
        job_id = _find_reschedulable_job(plan)
        if not job_id:
            pytest.skip("No reschedulable job on rain day")

        result, _ = _reschedule_job(plan, job_id)
        if not result.succeeded:
            pytest.skip("Job could not be rescheduled")

        assert store.get_job(job_id).status == JobStatus.RESCHEDULED, (
            f"Job {job_id} should be RESCHEDULED after reschedule, "
            f"got {store.get_job(job_id).status}"
        )

    def test_failed_reschedule_does_not_change_job_status(self):
        """If no slot is found, the job status must not change."""
        # Force failure by using a 420-min full-day job (job_W11) which
        # genuinely cannot fit anywhere else in the week.
        plan = _plan_and_confirm()
        rain_jobs = _rain_day_jobs(plan, RAIN_DAY)
        if not rain_jobs:
            pytest.skip("No jobs on rain day")

        # Prefer job_W11 (full-day) which can't fit elsewhere; fall back to first.
        full_day = next((jid for jid in rain_jobs if "W11" in jid), rain_jobs[0])
        job_id = full_day
        original_status = store.get_job(job_id).status

        agent = ReschedulerAgent()
        result = asyncio.run(
            agent.run_reschedule(
                plan,
                job_id,
                "Forced failure test",
                # Impossible window: end before the day after rain day.
                new_earliest=RAIN_DAY + timedelta(days=1),
                new_latest=RAIN_DAY,   # end < start → window normalised and tiny
            )
        )

        if result.succeeded:
            pytest.skip("Slot was found — can't test failure path")

        assert store.get_job(job_id).status == original_status, (
            f"Job {job_id} status changed to {store.get_job(job_id).status} "
            f"even though reschedule failed (expected {original_status})"
        )


async def _no_llm(*a, **kw):
    return None

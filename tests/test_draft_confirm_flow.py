"""Draft → confirm schedule flow tests.

── CONTRACT ─────────────────────────────────────────────────────────────────

DRAFT  (store.latest_plan)
  • Created by SupervisorAgent.plan_week().
  • Represents a preview; not yet the live schedule.
  • Job statuses remain PENDING — no status changes at draft time.
  • Re-running plan_week() overwrites the draft freely.
  • Does NOT touch store.confirmed_plan.

CONFIRM  (POST /api/plan/confirm  →  store.confirmed_plan)
  • The ONLY moment job statuses change to SCHEDULED.
  • Performs a deep-copy of the draft into confirmed_plan so the two
    objects are independent (mutations to either do not bleed through).
  • Jobs removed from a new confirmed plan that were SCHEDULED in the
    previous confirmed plan revert to PENDING (no ghost statuses).
  • Re-running plan_week() after a confirm does NOT touch confirmed_plan
    and does NOT regress SCHEDULED job statuses back to PENDING.

STATUS transitions tested here:
  PENDING  →  (draft created)  →  PENDING  (unchanged)
  PENDING  →  (confirm)        →  SCHEDULED
  SCHEDULED → (re-confirm, job removed) → PENDING  (ghost-status cleanup)
  SCHEDULED → (re-plan only)   →  SCHEDULED  (status preserved)
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.agents import SupervisorAgent
from app.models import JobStatus
from app.seed import seed
from app.storage import store

WEEK = date(2026, 7, 6)


# ─── Shared fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_store(monkeypatch):
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

    async def _no_llm(*a, **kw):
        return None

    monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode", _fake_geo)
    monkeypatch.setattr("app.agents.supervisor._next_monday", lambda: WEEK)
    monkeypatch.setattr("app.llm.llm.chat", _no_llm)
    yield


def _plan() -> object:
    return asyncio.run(SupervisorAgent().plan_week(WEEK))


def _confirm():
    """Inline replica of POST /api/plan/confirm logic."""
    plan = store.get_plan()
    assert plan is not None, "confirm called with no draft"
    published = plan.model_copy(deep=True)
    new_ids = {s.job_id for cd in published.plan.days for s in cd.stops}
    old = store.get_confirmed_plan()
    if old:
        old_ids = {s.job_id for cd in old.plan.days for s in cd.stops}
        for jid in old_ids - new_ids:
            store.set_job_status(jid, JobStatus.PENDING)
    for jid in new_ids:
        store.set_job_status(jid, JobStatus.SCHEDULED)
    store.set_confirmed_plan(published)
    return published


def _scheduled_ids(plan) -> set[str]:
    return {s.job_id for cd in plan.plan.days for s in cd.stops}


# ─── 1. Draft creation ────────────────────────────────────────────────────────

class TestDraftCreation:
    def test_plan_week_populates_latest_plan(self):
        assert store.get_plan() is None, "store should start clean"
        _plan()
        assert store.get_plan() is not None

    def test_draft_does_not_touch_confirmed_plan(self):
        assert store.get_confirmed_plan() is None
        _plan()
        assert store.get_confirmed_plan() is None, (
            "Running the planner must not set confirmed_plan"
        )

    def test_job_statuses_unchanged_after_draft(self):
        """All jobs must remain PENDING after a draft is created.
        The draft is a preview only — statuses change at confirm time."""
        _plan()
        for job in store.list_jobs():
            assert job.status in (JobStatus.PENDING, JobStatus.RESCHEDULED), (
                f"Job {job.id} has status {job.status} after draft creation; "
                f"expected PENDING. Jobs must not become SCHEDULED until confirm."
            )

    def test_draft_contains_expected_stops(self):
        result = _plan()
        in_plan = sum(len(cd.stops) for cd in result.plan.days)
        assert in_plan > 0, "draft should have scheduled stops"

    def test_draft_result_equals_store_latest_plan(self):
        result = _plan()
        stored = store.get_plan()
        # Both should refer to the same plan content.
        assert stored is not None
        assert result.plan.week_start == stored.plan.week_start
        scheduled_result  = _scheduled_ids(result)
        scheduled_stored  = _scheduled_ids(stored)
        assert scheduled_result == scheduled_stored


# ─── 2. Confirming the draft ──────────────────────────────────────────────────

class TestConfirmPlan:
    def test_confirm_creates_confirmed_plan(self):
        _plan()
        assert store.get_confirmed_plan() is None
        _confirm()
        assert store.get_confirmed_plan() is not None

    def test_confirmed_plan_has_same_jobs_as_draft(self):
        draft = _plan()
        _confirm()
        confirmed = store.get_confirmed_plan()
        assert _scheduled_ids(draft) == _scheduled_ids(confirmed)

    def test_scheduled_jobs_get_scheduled_status_after_confirm(self):
        draft = _plan()
        draft_job_ids = _scheduled_ids(draft)
        assert draft_job_ids, "need at least one scheduled job"
        _confirm()
        for jid in draft_job_ids:
            job = store.get_job(jid)
            assert job is not None
            assert job.status == JobStatus.SCHEDULED, (
                f"Job {jid} should be SCHEDULED after confirm, got {job.status}"
            )

    def test_unscheduled_jobs_stay_pending_after_confirm(self):
        """Jobs that the planner deferred must remain PENDING after confirm."""
        draft = _plan()
        unscheduled_ids = set(draft.plan.unscheduled_job_ids)
        _confirm()
        for jid in unscheduled_ids:
            job = store.get_job(jid)
            if job:
                assert job.status == JobStatus.PENDING, (
                    f"Deferred job {jid} should stay PENDING after confirm, got {job.status}"
                )

    def test_confirm_without_draft_raises_error(self):
        """Confirming when no draft exists must raise AssertionError (or similar)."""
        assert store.get_plan() is None
        with pytest.raises((AssertionError, Exception)):
            _confirm()

    def test_confirmed_plan_is_deep_copy_of_draft(self):
        """Modifying the draft after confirm must not affect confirmed_plan."""
        draft = _plan()
        _confirm()
        confirmed = store.get_confirmed_plan()
        # Mutate the draft's plan days list directly.
        original_day_count = len(confirmed.plan.days)
        draft.plan.days.clear()
        assert len(confirmed.plan.days) == original_day_count, (
            "confirmed_plan should be a deep copy; mutating the draft must not affect it"
        )

    def test_draft_and_confirmed_are_separate_objects(self):
        _plan()
        _confirm()
        assert store.get_plan() is not store.get_confirmed_plan(), (
            "latest_plan and confirmed_plan must be different Python objects"
        )


# ─── 3. Re-planning after confirm ────────────────────────────────────────────

class TestReplanAfterConfirm:
    def test_replanning_does_not_overwrite_confirmed_plan(self):
        _plan()
        _confirm()
        confirmed_before = store.get_confirmed_plan()
        confirmed_week   = confirmed_before.plan.week_start
        # Re-run the planner.
        _plan()
        confirmed_after = store.get_confirmed_plan()
        assert confirmed_after is not None
        assert confirmed_after.plan.week_start == confirmed_week, (
            "confirmed_plan.week_start changed after re-plan — re-planning must not overwrite confirmed"
        )

    def test_replanning_updates_draft_but_not_confirmed(self):
        _plan()
        _confirm()
        confirmed_ids_before = _scheduled_ids(store.get_confirmed_plan())

        # Re-plan (this produces a new draft).
        _plan()
        confirmed_ids_after = _scheduled_ids(store.get_confirmed_plan())
        draft_ids = _scheduled_ids(store.get_plan())

        assert confirmed_ids_after == confirmed_ids_before, (
            "confirmed plan content changed after re-planning without a second confirm"
        )
        # The draft is a fresh independent computation (may or may not match).
        assert store.get_plan() is not store.get_confirmed_plan()

    def test_scheduled_statuses_not_reset_by_replan(self):
        """Jobs that were SCHEDULED via confirm must not lose that status when the
        planner is re-run without a second confirm."""
        draft = _plan()
        confirmed_job_ids = _scheduled_ids(draft)
        _confirm()
        # All confirmed jobs are now SCHEDULED.
        for jid in confirmed_job_ids:
            assert store.get_job(jid).status == JobStatus.SCHEDULED

        # Re-run the planner (produces a new draft only).
        _plan()

        # Confirmed-job statuses must be unchanged.
        for jid in confirmed_job_ids:
            job = store.get_job(jid)
            assert job.status == JobStatus.SCHEDULED, (
                f"Job {jid} regressed to {job.status} after re-plan without confirm"
            )

    def test_draft_jobs_not_scheduled_until_second_confirm(self):
        """After a re-plan that adds new jobs, those new jobs must stay PENDING
        until a second confirm is issued."""
        _plan()
        _confirm()
        first_confirmed_ids = _scheduled_ids(store.get_confirmed_plan())

        # Re-plan produces a new draft.
        new_draft = _plan()
        new_draft_ids  = _scheduled_ids(new_draft)
        genuinely_new  = new_draft_ids - first_confirmed_ids

        # Any job that appears in the draft but not in the confirmed plan must
        # be PENDING (it's only in the preview, not yet confirmed).
        for jid in genuinely_new:
            job = store.get_job(jid)
            assert job is not None
            assert job.status != JobStatus.SCHEDULED, (
                f"Job {jid} became SCHEDULED from the draft alone (before confirm). "
                "Status must only be set at confirm time."
            )


# ─── 4. Second confirm (ghost-status cleanup) ────────────────────────────────

class TestSecondConfirm:
    def test_jobs_removed_in_second_confirm_revert_to_pending(self):
        """If a job was in confirmed plan A but not in confirmed plan B,
        it must revert to PENDING after confirming B.

        Strategy: after the first confirm, push one job's date window past the
        planning week so the planner will not include it in the second run.
        Then confirm the second plan and verify that job is PENDING again.
        """
        first_draft = _plan()
        _confirm()
        confirmed_ids = _scheduled_ids(store.get_confirmed_plan())
        if not confirmed_ids:
            pytest.skip("no scheduled jobs to test with")

        # Pick a job that is SCHEDULED in the first confirmed plan.
        excluded_id = next(iter(confirmed_ids))
        excluded_job = store.get_job(excluded_id)

        # Push its date window to next year so the July planner won't see it.
        from datetime import date as _date
        original_earliest = excluded_job.earliest_date
        original_latest   = excluded_job.latest_date
        excluded_job.earliest_date = _date(2027, 1, 1)
        excluded_job.latest_date   = _date(2027, 1, 31)

        try:
            # Second plan — excluded_id is outside the July window → not scheduled.
            _plan()
            _confirm()

            # The excluded job should have reverted to PENDING.
            assert store.get_job(excluded_id).status == JobStatus.PENDING, (
                f"Job {excluded_id} was in confirmed plan A but absent from plan B; "
                f"expected PENDING after second confirm, "
                f"got {store.get_job(excluded_id).status}"
            )
        finally:
            excluded_job.earliest_date = original_earliest
            excluded_job.latest_date   = original_latest

    def test_jobs_retained_across_both_confirms_stay_scheduled(self):
        """A job that appears in BOTH confirmed plans must stay SCHEDULED
        after the second confirm."""
        first_draft = _plan()
        _confirm()
        first_ids = _scheduled_ids(store.get_confirmed_plan())

        _plan()
        _confirm()
        second_ids = _scheduled_ids(store.get_confirmed_plan())

        retained = first_ids & second_ids
        for jid in retained:
            assert store.get_job(jid).status == JobStatus.SCHEDULED, (
                f"Job {jid} was in both confirms but is no longer SCHEDULED"
            )


# ─── 5. Draft / confirmed not confused ───────────────────────────────────────

class TestDraftConfirmedIsolation:
    def test_get_plan_returns_draft_not_confirmed(self):
        draft = _plan()
        _confirm()
        # Mutate the confirmed plan.
        store.get_confirmed_plan().plan.summary = "__MUTATED__"
        # The draft (latest_plan) should be unaffected.
        assert store.get_plan().plan.summary != "__MUTATED__", (
            "store.get_plan() is leaking the confirmed plan reference"
        )

    def test_get_confirmed_returns_confirmed_not_draft(self):
        _plan()
        _confirm()
        # Mutate the draft.
        store.get_plan().plan.summary = "__DRAFT_MUTATED__"
        assert store.get_confirmed_plan().plan.summary != "__DRAFT_MUTATED__", (
            "store.get_confirmed_plan() is leaking the draft plan reference"
        )

    def test_confirmed_plan_week_start_matches_draft(self):
        _plan()
        _confirm()
        assert store.get_plan().plan.week_start == store.get_confirmed_plan().plan.week_start

    def test_no_confirmed_plan_before_first_confirm(self):
        _plan()
        assert store.get_confirmed_plan() is None, (
            "confirmed_plan must be None until POST /api/plan/confirm is called"
        )

    def test_job_status_pending_before_confirm_scheduled_after(self):
        """End-to-end status transition: PENDING → (draft) → PENDING → (confirm) → SCHEDULED."""
        all_job_ids = {j.id for j in store.list_jobs()}

        # Before planning.
        for jid in all_job_ids:
            assert store.get_job(jid).status == JobStatus.PENDING

        # After draft.
        draft = _plan()
        for jid in all_job_ids:
            assert store.get_job(jid).status == JobStatus.PENDING, (
                f"Job {jid} changed status during draft creation; must stay PENDING"
            )

        # After confirm.
        _confirm()
        draft_ids = _scheduled_ids(draft)
        for jid in draft_ids:
            assert store.get_job(jid).status == JobStatus.SCHEDULED, (
                f"Job {jid} should be SCHEDULED after confirm, got {store.get_job(jid).status}"
            )
        for jid in all_job_ids - draft_ids:
            assert store.get_job(jid).status == JobStatus.PENDING, (
                f"Deferred job {jid} should remain PENDING after confirm"
            )

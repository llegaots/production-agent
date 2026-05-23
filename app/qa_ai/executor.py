"""Execute AI-designed QA scenarios against the real agent stack."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from ..agents import ReschedulerAgent, SupervisorAgent
from ..agents.supervisor import _next_monday
from ..models import PlanResult
from ..reorganize import parse_reorganize_instruction
from ..scheduling_prefs import SchedulingMode, parse_mode
from ..seed import seed, SEED_WEEK_START
from ..storage import store
from ..supabase_store import persist_plan
from .schedule_snapshot import plan_result_context
from .test_job_manager import delete_test_jobs, insert_test_jobs

logger = logging.getLogger(__name__)


class CaseExecutionResult:
    def __init__(self) -> None:
        self.plan_results: list[PlanResult] = []
        self.events: list[dict[str, Any]] = []
        self.final_plan: Optional[PlanResult] = None
        self.scheduling_mode: Optional[str] = None
        self.owner_instructions: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_count": len(self.plan_results),
            "final_plan": plan_result_context(
                self.final_plan,
                scheduling_mode=self.scheduling_mode,
                owner_instruction=" | ".join(self.owner_instructions) or None,
            ),
            "steps_executed": self.events,
        }


async def execute_case(
    case: dict,
    *,
    week_start: Optional[date] = None,
    reset_seed: bool = True,
    run_id: str = "qa",
) -> CaseExecutionResult:
    ws = week_start or SEED_WEEK_START
    out = CaseExecutionResult()

    # Always reset to a clean known state before each case.
    seed(reset=True)

    # Disable LLM for the scheduler pipeline during QA execution.
    # The planning agents (ClientComms, PlanReviewer) make 40-60 LLM calls
    # per plan run (one per scheduled job × critic iterations). We don't need
    # polished client messages to evaluate schedule logic — template fallbacks
    # are sufficient. The critic and designer run AFTER this context exits,
    # so they still use the real LLM.
    from ..llm import llm as _llm
    _original_chat = _llm.chat

    async def _noop(*a, **kw):
        return None

    _llm.chat = _noop

    # Also skip real geocoding during QA — use stored coords to avoid
    # Google API round-trips for every test job address (adds 2-5s per job).
    from ..geocode import geocoder as _geocoder
    _original_geocode = _geocoder.geocode

    async def _fast_geocode(address: str):
        from ..geocode import GeocodeResult
        # Try to find exact match in current store jobs (test jobs have default coords).
        for j in store.list_jobs():
            if j.address == address:
                return GeocodeResult(
                    input_address=address, success=True,
                    lat=j.lat, lng=j.lng,
                    formatted_address=address, confidence=0.9,
                    needs_review=False, in_service_area=True,
                    location_type="ROOFTOP", postal_code="H9X",
                    province="QC", source="cache",
                )
        from ..seed import BASE_LAT, BASE_LNG
        return GeocodeResult(
            input_address=address, success=True,
            lat=BASE_LAT, lng=BASE_LNG,
            formatted_address=address, confidence=0.8,
            needs_review=False, in_service_area=True,
            location_type="APPROXIMATE", postal_code="H9X",
            province="QC", source="cache",
        )

    _geocoder.geocode = _fast_geocode

    # If the case designer provided custom test jobs, insert them into the
    # store AND Supabase so the scheduler sees them as real persisted jobs.
    test_job_defs = case.get("test_jobs") or []
    inserted_job_ids: list[str] = []
    if test_job_defs:
        try:
            inserted_job_ids = await insert_test_jobs(test_job_defs, run_id, ws)
            logger.info(
                "QA[%s] inserted %d test jobs: %s",
                run_id, len(inserted_job_ids), inserted_job_ids,
            )
            # Verify inserted jobs are actually retrievable from store before scheduling.
            missing_from_store = [jid for jid in inserted_job_ids if store.get_job(jid) is None]
            if missing_from_store:
                logger.error(
                    "QA[%s] test job insertion FAILED for %s — not found in store after insert",
                    run_id, missing_from_store,
                )
            out.events.append({
                "step": -1,
                "action": "test_jobs_inserted",
                "count": len(inserted_job_ids),
                "ids": inserted_job_ids,
                "store_verified": len(missing_from_store) == 0,
                "missing_from_store": missing_from_store,
            })
        except Exception as exc:
            logger.error("QA[%s] test job insertion raised an exception: %s", run_id, exc)
            inserted_job_ids = []
            out.events.append({
                "step": -1,
                "action": "test_jobs_insertion_failed",
                "error": str(exc),
            })

    steps = case.get("steps") or []
    plan: Optional[PlanResult] = store.get_plan()

    try:
        for i, step in enumerate(steps):
            action = (step.get("action") or "").lower().replace("-", "_")
            evt: dict[str, Any] = {"step": i, "action": action}

            if action == "plan":
                mode = parse_mode(step.get("scheduling_mode") or "balanced")
                out.scheduling_mode = mode.value
                store.scheduling_mode = mode
                sup = SupervisorAgent()
                plan = await sup.plan_week(ws, scheduling_mode=mode)
                out.plan_results.append(plan)
                out.final_plan = plan
                store.set_plan(plan)
                try:
                    await persist_plan(plan)
                except Exception:
                    pass
                evt["scheduling_mode"] = mode.value

            elif action == "reorganize":
                text = step.get("instruction") or step.get("text") or ""
                out.owner_instructions.append(text)
                intent = parse_reorganize_instruction(text, ws)
                out.scheduling_mode = intent.scheduling_mode.value
                store.scheduling_mode = intent.scheduling_mode
                evt["parsed_intent"] = {
                    "mode": intent.scheduling_mode.value,
                    "job_id": intent.job_id,
                    "target_day": intent.target_day.isoformat() if intent.target_day else None,
                }
                if intent.job_id and plan:
                    agent = ReschedulerAgent()
                    plan = store.get_plan() or plan
                    res = await agent.run_reschedule(
                        plan,
                        intent.job_id,
                        intent.reason,
                        preferred_day=intent.target_day,
                    )
                    plan = store.get_plan()
                    out.final_plan = plan
                    evt["reschedule"] = {
                        "succeeded": res.succeeded,
                        "new_day": res.new_day.isoformat() if res.new_day else None,
                        "new_crew_id": res.new_crew_id,
                    }
                else:
                    sup = SupervisorAgent()
                    plan = await sup.plan_week(ws, scheduling_mode=intent.scheduling_mode)
                    out.plan_results.append(plan)
                    out.final_plan = plan
                    try:
                        await persist_plan(plan)
                    except Exception:
                        pass

            elif action == "reschedule":
                job_id = step.get("job_id")
                reason = step.get("reason") or "Owner requested change"
                if not plan:
                    evt["error"] = "no_plan_before_reschedule"
                elif job_id:
                    agent = ReschedulerAgent()
                    pref = step.get("preferred_day")
                    pref_date = date.fromisoformat(pref) if pref else None
                    res = await agent.run_reschedule(
                        plan,
                        job_id,
                        reason,
                        preferred_day=pref_date,
                    )
                    plan = store.get_plan()
                    out.final_plan = plan
                    evt["reschedule"] = {
                        "job_id": job_id,
                        "succeeded": res.succeeded,
                        "new_day": res.new_day.isoformat() if res.new_day else None,
                    }

            elif action == "plan_then_reschedule":
                mode = parse_mode(step.get("scheduling_mode") or "balanced")
                job_id = step.get("job_id")
                reason = step.get("reason") or "QA scenario disruption"
                sup = SupervisorAgent()
                plan = await sup.plan_week(ws, scheduling_mode=mode)
                out.plan_results.append(plan)
                out.scheduling_mode = mode.value
                if job_id:
                    agent = ReschedulerAgent()
                    res = await agent.run_reschedule(plan, job_id, reason)
                    plan = store.get_plan()
                    evt["reschedule"] = {"succeeded": res.succeeded}
                out.final_plan = plan

            else:
                evt["error"] = f"unknown_action:{action}"

            out.events.append(evt)

        if not out.final_plan and plan:
            out.final_plan = plan

    finally:
        # Always restore, even if an exception fires mid-execution.
        _llm.chat = _original_chat
        _geocoder.geocode = _original_geocode

    # Verify that all inserted test jobs appear in the final plan before cleanup.
    # This regression check catches silent scheduling failures early.
    if inserted_job_ids and out.final_plan:
        scheduled_ids = {
            s.job_id
            for d in out.final_plan.plan.days
            for s in d.stops
        }
        unscheduled_ids = set(out.final_plan.plan.unscheduled_job_ids)
        missing_test_jobs = [
            jid for jid in inserted_job_ids
            if jid not in scheduled_ids and jid not in unscheduled_ids
        ]
        scheduled_test_jobs = [jid for jid in inserted_job_ids if jid in scheduled_ids]
        deferred_test_jobs = [jid for jid in inserted_job_ids if jid in unscheduled_ids]

        if missing_test_jobs:
            logger.error(
                "QA[%s] REGRESSION: %d test job(s) vanished from plan output (not scheduled, "
                "not unscheduled): %s. Planner may have silently dropped them.",
                run_id, len(missing_test_jobs), missing_test_jobs,
            )
        logger.info(
            "QA[%s] test job outcome — scheduled: %s, deferred: %s, missing: %s",
            run_id, scheduled_test_jobs, deferred_test_jobs, missing_test_jobs,
        )
        out.events.append({
            "step": "regression_check",
            "action": "test_job_regression",
            "inserted": inserted_job_ids,
            "scheduled": scheduled_test_jobs,
            "deferred": deferred_test_jobs,
            "missing": missing_test_jobs,
            "passed": len(missing_test_jobs) == 0,
        })

    # Clean up test jobs from store and Supabase after the case completes.
    if inserted_job_ids:
        await delete_test_jobs(inserted_job_ids)

    return out


async def apply_owner_retry(retry: dict, *, week_start: date) -> CaseExecutionResult:
    """Run a critic-suggested owner retry (reorganize or replan)."""
    action = (retry.get("action") or "reorganize").lower()
    case = {
        "fingerprint": "retry",
        "title": "Critic-suggested owner retry",
        "steps": [],
    }
    if action == "plan":
        mode = retry.get("instruction_or_mode") or retry.get("mode") or "balanced"
        case["steps"] = [{"action": "plan", "scheduling_mode": mode}]
    else:
        instr = retry.get("instruction_or_mode") or retry.get("instruction") or "reorganize the week"
        case["steps"] = [{"action": "reorganize", "instruction": instr}]
    return await execute_case(case, week_start=week_start, reset_seed=False)

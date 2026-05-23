"""Execute AI-designed QA scenarios against the real agent stack."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..agents import ReschedulerAgent, SupervisorAgent
from ..agents.supervisor import _next_monday
from ..models import Job, PlanResult
from ..reorganize import parse_reorganize_instruction
from ..scheduling_prefs import SchedulingMode, parse_mode
from ..seed import seed, SEED_WEEK_START
from ..storage import store
from ..supabase_store import persist_plan
from .schedule_snapshot import plan_result_context
from .test_job_manager import delete_test_jobs, insert_test_jobs

class CaseExecutionResult:
    def __init__(self) -> None:
        self.plan_results: list[PlanResult] = []
        self.events: list[dict[str, Any]] = []
        self.final_plan: Optional[PlanResult] = None
        self.scheduling_mode: Optional[str] = None
        self.owner_instructions: list[str] = []
        self.inserted_job_ids: list[str] = []
        self.job_lookup: dict[str, Job] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_count": len(self.plan_results),
            "final_plan": plan_result_context(
                self.final_plan,
                scheduling_mode=self.scheduling_mode,
                owner_instruction=" | ".join(self.owner_instructions) or None,
                job_lookup=self.job_lookup or None,
            ),
            "steps_executed": self.events,
            "inserted_job_ids": self.inserted_job_ids,
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
    inserted_job_ids: list[str] = []
    seed_job_backup: dict[str, Job] = {}

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

    try:
        # If the case designer provided custom test jobs, insert them into the
        # store AND Supabase so the scheduler sees them as real persisted jobs.
        test_job_defs = case.get("test_jobs") or []
        if test_job_defs:
            inserted_job_ids = await insert_test_jobs(test_job_defs, run_id, ws)
            out.inserted_job_ids = inserted_job_ids
            out.events.append({
                "step": -1,
                "action": "test_jobs_inserted",
                "count": len(inserted_job_ids),
                "ids": inserted_job_ids,
            })

            # Focus the scenario: hide seed jobs so the planner only sees the
            # test jobs the case designer defined (avoids noise from 27+ seed jobs).
            for jid, job in list(store.jobs.items()):
                if not jid.startswith("qa_"):
                    seed_job_backup[jid] = job
                    del store.jobs[jid]

            # Cache job objects for schedule snapshot (survives later cleanup).
            for jid in inserted_job_ids:
                job = store.get_job(jid)
                if job:
                    out.job_lookup[jid] = job
    except Exception:
        inserted_job_ids = []
        out.inserted_job_ids = []

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
        # Restore seed jobs removed for focused test scenarios.
        for jid, job in seed_job_backup.items():
            store.jobs[jid] = job

    # Test jobs are cleaned up by the runner AFTER the critic snapshot is built.
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

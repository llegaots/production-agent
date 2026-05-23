"""Execute AI-designed QA scenarios against the real agent stack.

AI QA is Supabase-only for jobs: no seed dataset (job_W*, job_G*, etc.).
Each case defines test_jobs that are inserted as qa_* rows, executed, critiqued,
then deleted.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..agents import ReschedulerAgent, SupervisorAgent
from ..models import Job, PlanResult
from ..reorganize import parse_reorganize_instruction
from ..scheduling_prefs import SchedulingMode, parse_mode
from ..seed import SEED_WEEK_START
from ..storage import store
from .schedule_snapshot import plan_result_context
from .store_setup import load_reference_data_only, normalize_case, normalize_qa_job_id
from .test_job_manager import insert_test_jobs


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
    run_id: str = "qa",
) -> CaseExecutionResult:
    ws = week_start or SEED_WEEK_START
    case = normalize_case(case)
    out = CaseExecutionResult()

    # Reference data only — crews/clients/equipment, zero seed jobs.
    load_reference_data_only()

    from ..llm import llm as _llm
    _original_chat = _llm.chat

    async def _noop(*a, **kw):
        return None

    _llm.chat = _noop

    from ..geocode import geocoder as _geocoder
    _original_geocode = _geocoder.geocode

    async def _fast_geocode(address: str):
        from ..geocode import GeocodeResult
        from ..seed import BASE_LAT, BASE_LNG

        for j in store.list_jobs():
            if j.address == address:
                return GeocodeResult(
                    input_address=address,
                    success=True,
                    lat=j.lat,
                    lng=j.lng,
                    formatted_address=address,
                    confidence=0.9,
                    needs_review=False,
                    in_service_area=True,
                    location_type="ROOFTOP",
                    postal_code="H9X",
                    province="QC",
                    source="cache",
                )
        return GeocodeResult(
            input_address=address,
            success=True,
            lat=BASE_LAT,
            lng=BASE_LNG,
            formatted_address=address,
            confidence=0.8,
            needs_review=False,
            in_service_area=True,
            location_type="APPROXIMATE",
            postal_code="H9X",
            province="QC",
            source="cache",
        )

    _geocoder.geocode = _fast_geocode

    test_job_defs = case.get("test_jobs") or []
    inserted_job_ids: list[str] = []

    try:
        if not test_job_defs:
            out.events.append({"step": -1, "action": "error", "error": "no_test_jobs"})
            return out

        inserted_job_ids = await insert_test_jobs(test_job_defs, run_id, ws)
        out.inserted_job_ids = inserted_job_ids
        out.events.append({
            "step": -1,
            "action": "test_jobs_inserted",
            "count": len(inserted_job_ids),
            "ids": inserted_job_ids,
        })

        for jid in inserted_job_ids:
            job = store.get_job(jid)
            if job:
                out.job_lookup[jid] = job

        steps = case.get("steps") or [{"action": "plan", "scheduling_mode": "balanced"}]
        plan: Optional[PlanResult] = None

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
                        normalize_qa_job_id(intent.job_id),
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

            elif action == "reschedule":
                job_id = normalize_qa_job_id(step.get("job_id") or "")
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
                job_id = normalize_qa_job_id(step.get("job_id") or "")
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
        _llm.chat = _original_chat
        _geocoder.geocode = _original_geocode

    return out


async def apply_owner_retry(
    retry: dict,
    *,
    week_start: date,
    case: dict,
) -> CaseExecutionResult:
    """Run a critic-suggested owner retry, preserving the case test_jobs."""
    action = (retry.get("action") or "reorganize").lower()
    merged = normalize_case(dict(case))
    steps = list(merged.get("steps") or [])
    if action == "plan":
        mode = retry.get("instruction_or_mode") or retry.get("mode") or "balanced"
        steps = [{"action": "plan", "scheduling_mode": mode}]
    else:
        instr = retry.get("instruction_or_mode") or retry.get("instruction") or "reorganize the week"
        steps = [{"action": "reorganize", "instruction": instr}]
    merged["steps"] = steps
    return await execute_case(merged, week_start=week_start, run_id=case.get("fingerprint", "retry"))

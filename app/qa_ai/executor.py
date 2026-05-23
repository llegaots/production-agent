"""Execute AI-designed QA scenarios against the real agent stack."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..agents import ReschedulerAgent, SupervisorAgent
from ..agents.base import haversine_km
from ..agents.supervisor import _next_monday
from ..models import PlanResult
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
        # Pre-built snapshot captured while test jobs are still in the store,
        # so stop-level job lookups don't return {"job_id": "unknown"}.
        self._final_plan_context: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_count": len(self.plan_results),
            "final_plan": (
                self._final_plan_context
                if self._final_plan_context is not None
                else plan_result_context(
                    self.final_plan,
                    scheduling_mode=self.scheduling_mode,
                    owner_instruction=" | ".join(self.owner_instructions) or None,
                )
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

    try:
        # If the case designer provided custom test jobs, insert them into the
        # store AND Supabase so the scheduler sees them as real persisted jobs.
        test_job_defs = case.get("test_jobs") or []
        inserted_job_ids: list[str] = []
        if test_job_defs:
            inserted_job_ids = await insert_test_jobs(test_job_defs, run_id, ws)
            out.events.append({
                "step": -1,
                "action": "test_jobs_inserted",
                "count": len(inserted_job_ids),
                "ids": inserted_job_ids,
            })

            # Fix: remove seed jobs from the store so the planner only schedules
            # the defined test jobs, not the 27-job seed dataset. This prevents
            # the planner from fabricating unrelated job IDs into the schedule.
            seed_job_ids = [
                jid for jid in list(store.jobs.keys())
                if not jid.startswith("qa_")
            ]
            for jid in seed_job_ids:
                store.jobs.pop(jid, None)
            out.events.append({
                "step": -1,
                "action": "seed_jobs_removed",
                "count": len(seed_job_ids),
                "reason": "test_jobs provided — planner restricted to test job set only",
            })
    except Exception:
        inserted_job_ids = []

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

                # Validate and repair the plan when test_jobs are defined.
                if inserted_job_ids:
                    plan = _validate_plan_against_test_jobs(plan, inserted_job_ids, evt)

                out.plan_results.append(plan)
                out.final_plan = plan
                store.set_plan(plan)
                try:
                    await persist_plan(plan)
                except Exception:
                    pass
                evt["scheduling_mode"] = mode.value

                # Geo-routing pre-flight: verify jobs are grouped by geographic
                # zone when geo_first mode is active and test jobs are defined.
                if inserted_job_ids and mode == SchedulingMode.GEO_FIRST:
                    evt["geo_routing_check"] = _check_geo_routing(plan, inserted_job_ids)

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
                    if inserted_job_ids:
                        plan = _validate_plan_against_test_jobs(plan, inserted_job_ids, evt)
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

    # Capture the plan snapshot while test jobs are still in the store so that
    # stop-level job lookups in schedule_snapshot.py can resolve every job_id.
    # Without this, delete_test_jobs (below) removes the jobs from the store
    # before to_dict() runs, causing every stop to show job_id='unknown'.
    if inserted_job_ids and out.final_plan:
        out._final_plan_context = plan_result_context(
            out.final_plan,
            scheduling_mode=out.scheduling_mode,
            owner_instruction=" | ".join(out.owner_instructions) or None,
        )

    # Clean up test jobs from store and Supabase after the case completes.
    if inserted_job_ids:
        await delete_test_jobs(inserted_job_ids)

    return out


def _validate_plan_against_test_jobs(
    plan: PlanResult,
    inserted_job_ids: list[str],
    evt: dict[str, Any],
) -> PlanResult:
    """Remove any scheduled stops whose job_id is not in the test_jobs set,
    and ensure unscheduled_job_ids only lists test job IDs.

    This prevents seed-dataset job IDs (job_W08, job_P01, etc.) from
    appearing in the schedule when the case defined only a small test set.
    Also ensures every test job appears in exactly one of: scheduled stops
    or unscheduled_job_ids.
    """
    valid_ids: set[str] = set(inserted_job_ids)
    fabricated_ids: list[str] = []

    # Remove any stop that references a job outside the test set.
    for cd in plan.plan.days:
        kept = [s for s in cd.stops if s.job_id in valid_ids]
        removed = [s.job_id for s in cd.stops if s.job_id not in valid_ids]
        fabricated_ids.extend(removed)
        cd.stops = kept
        cd.total_work_minutes = sum(s.duration_minutes for s in kept)

    # Remove crew_days that have no stops left after filtering.
    plan.plan.days = [cd for cd in plan.plan.days if cd.stops]

    # Filter unscheduled_job_ids: only keep entries that belong to the test set.
    unknown_unscheduled = [
        jid for jid in plan.plan.unscheduled_job_ids if jid not in valid_ids
    ]
    plan.plan.unscheduled_job_ids = [
        jid for jid in plan.plan.unscheduled_job_ids if jid in valid_ids
    ]

    # Any test job that is neither scheduled nor unscheduled must be accounted for.
    scheduled_ids: set[str] = {
        s.job_id for cd in plan.plan.days for s in cd.stops
    }
    already_unscheduled: set[str] = set(plan.plan.unscheduled_job_ids)
    for jid in valid_ids:
        if jid not in scheduled_ids and jid not in already_unscheduled:
            plan.plan.unscheduled_job_ids.append(jid)

    evt["test_job_validation"] = {
        "valid_ids": sorted(valid_ids),
        "fabricated_stops_removed": sorted(set(fabricated_ids)),
        "unknown_unscheduled_removed": unknown_unscheduled,
        "scheduled_count": len(scheduled_ids & valid_ids),
        "unscheduled_count": len(plan.plan.unscheduled_job_ids),
    }
    return plan


def _check_geo_routing(plan: PlanResult, inserted_job_ids: list[str]) -> dict[str, Any]:
    """Pre-flight check for geo_routing mode.

    Verifies that the schedule actually groups jobs by geographic zone by
    measuring average intra-crew-day drive distance for each crew-day and
    flagging if cross-zone travel looks excessive (> 15 km per crew-day).
    """
    GEO_THRESHOLD_KM = 15.0
    issues: list[str] = []
    crew_day_stats: list[dict] = []

    for cd in plan.plan.days:
        if len(cd.stops) < 2:
            continue
        job_locs: list[tuple[float, float]] = []
        for s in cd.stops:
            j = store.get_job(s.job_id)
            if j:
                job_locs.append((j.lat, j.lng))

        if len(job_locs) < 2:
            continue

        # Compute total route distance among the stops (chained)
        route_km = sum(
            haversine_km(job_locs[i][0], job_locs[i][1],
                         job_locs[i + 1][0], job_locs[i + 1][1])
            for i in range(len(job_locs) - 1)
        )
        stat = {
            "crew_id": cd.crew_id,
            "day": cd.day.isoformat(),
            "stops": len(cd.stops),
            "route_km": round(route_km, 2),
            "exceeds_threshold": route_km > GEO_THRESHOLD_KM,
        }
        crew_day_stats.append(stat)
        if route_km > GEO_THRESHOLD_KM:
            issues.append(
                f"{cd.crew_id} on {cd.day.isoformat()}: {route_km:.1f} km "
                f"route exceeds {GEO_THRESHOLD_KM} km geo threshold"
            )

    return {
        "threshold_km": GEO_THRESHOLD_KM,
        "crew_day_stats": crew_day_stats,
        "issues": issues,
        "passed": len(issues) == 0,
    }


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

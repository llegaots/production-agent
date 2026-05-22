"""Execute AI-designed QA scenarios against the real agent stack."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..agents import ReschedulerAgent, SupervisorAgent
from ..agents.supervisor import _next_monday
from ..models import PlanResult
from ..reorganize import parse_reorganize_instruction
from ..scheduling_prefs import SchedulingMode, parse_mode
from ..seed import seed
from ..storage import store
from ..supabase_store import persist_plan
from .schedule_snapshot import plan_result_context


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
) -> CaseExecutionResult:
    ws = week_start or _next_monday()
    out = CaseExecutionResult()

    setup = case.get("setup") or {}
    if reset_seed or setup.get("reset_seed", True):
        seed(reset=True)

    steps = case.get("steps") or []
    plan: Optional[PlanResult] = store.get_plan()

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

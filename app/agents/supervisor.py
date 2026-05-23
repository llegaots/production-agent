"""SupervisorAgent - orchestrates the multi-agent weekly plan.

Anthropic pattern: **Orchestrator-workers**.

The supervisor runs the agents in four phases:

    Phase 1: sequential       GeoCluster -> CrewMatch
    Phase 2: parallel         Equipment  ||  TimeBudget       (sectioning)
    Phase 3: comms pipeline   ClientComms (route -> draft -> critic||guardrail -> revise?)
    Phase 4: evaluator        PlanReviewer

It threads a typed ``AgentContext`` through every step, aggregates
conflicts produced by each specialist, and streams agent events to the
caller so the UI can render a live transcript of the run.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from ..geocode import geocoder
from ..llm import llm
from ..supabase_client import supabase
from ..models import (
    CrewDay,
    MessageQuality,
    PlanResult,
    PlanReview,
    WeekPlan,
)
from ..scheduling_prefs import SchedulingMode, parse_mode
from ..storage import store
from .base import Agent, AgentContext, EventEmitter, llm_trace_callback, week_days
from .client_comms import ClientCommsAgent
from .crew_match import CrewMatchAgent
from .equipment import EquipmentAgent
from .geo_cluster import GeoClusterAgent
from .plan_reviewer import PlanReviewerAgent
from .time_budget import TimeBudgetAgent

logger = logging.getLogger(__name__)


def _next_monday(today: Optional[date] = None) -> date:
    """Return the Monday of the NEXT planning week.

    If today is Monday, the next planning Monday is 7 days away.
    This is used for live production planning and for the QA executor's
    fallback when no explicit week_start is provided.
    """
    today = today or date.today()
    days_ahead = (7 - today.weekday()) % 7  # days until Monday
    if days_ahead == 0:
        days_ahead = 7  # today IS Monday → plan for next week
    return today + timedelta(days=days_ahead)


class SupervisorAgent(Agent):
    """Runs the full pipeline and assembles a ``PlanResult``."""

    name = "SupervisorAgent"

    def __init__(self) -> None:
        self.geo = GeoClusterAgent()
        self.crew = CrewMatchAgent()
        self.equipment = EquipmentAgent()
        self.budget = TimeBudgetAgent()
        self.comms = ClientCommsAgent()
        self.reviewer = PlanReviewerAgent()

    async def plan_week(
        self,
        week_start: Optional[date] = None,
        emitter: Optional[EventEmitter] = None,
        scheduling_mode: Optional[SchedulingMode | str] = None,
    ) -> PlanResult:
        ws = week_start or _next_monday()
        week_end = week_days(ws)[-1]   # last working day of the 5-day window
        jobs = [
            j for j in store.list_jobs()
            if j.status.value in ("pending", "scheduled", "rescheduled")
            # Only offer jobs whose date window overlaps with the planning week.
            # A job with earliest_date > week_end is not due yet; one with
            # latest_date < ws is already overdue (handled separately).
            # Guard against None dates (should not happen with valid data but
            # defensive handling prevents silent inclusion of undated jobs).
            and j.earliest_date is not None
            and j.latest_date is not None
            and j.earliest_date <= week_end
            and j.latest_date >= ws
        ]
        crews = store.list_crews()
        mode = (
            scheduling_mode
            if isinstance(scheduling_mode, SchedulingMode)
            else parse_mode(scheduling_mode)
            if scheduling_mode
            else store.scheduling_mode
        )
        store.scheduling_mode = mode

        ctx = AgentContext(
            week_start=ws, crews=crews, jobs=jobs, scheduling_mode=mode, emitter=emitter
        )
        ctx.blackboard["scheduling_mode"] = mode

        await ctx.emit(
            "System",
            "config",
            f"Runtime: LLM {'enabled' if llm.enabled else 'off'} "
            f"({llm.provider_label} · {llm.model if llm.enabled else 'templates'}), "
            f"Geocoding {'enabled' if geocoder.enabled else 'off'}, "
            f"Supabase {'enabled' if supabase.enabled else 'off'}.",
            detail={
                "llm_enabled": llm.enabled,
                "llm_provider": llm.provider,
                "llm_model": llm.model if llm.enabled else None,
                "geocoding_enabled": geocoder.enabled,
                "supabase_enabled": supabase.enabled,
                "jobs": len(jobs),
                "crews": len(crews),
                "scheduling_mode": mode.value,
            },
            kind="system",
        )
        await ctx.emit(
            self.name,
            "start",
            f"Planning week starting {ws.isoformat()} with {len(jobs)} jobs across {len(crews)} crews.",
        )

        # Phase 1 - sequential dependencies: geo cluster -> crew match
        await self.geo.run(ctx)
        await self.crew.run(ctx)

        # Phase 2 - parallel sectioning: equipment + time-budget validate
        # independent aspects of the draft plan. Anthropic's "parallelization
        # (sectioning)" pattern: each agent focuses on one specific aspect.
        await ctx.emit(
            self.name,
            "parallel",
            "Running Equipment and TimeBudget validators in parallel.",
        )
        await asyncio.gather(self.equipment.run(ctx), self.budget.run(ctx))

        # Post Phase 2: evict jobs that EquipmentAgent flagged as unresolvable
        # equipment conflicts from crew_days so no crew is asked to operate
        # without its required equipment.
        await self._evict_equipment_conflicts(ctx)

        # Phase 3 - comms pipeline (router -> draft -> guardrail || critic -> redraft).
        await self.comms.run(ctx)

        # Phase 4 - evaluator on the assembled plan.
        await self.reviewer.run(ctx)

        crew_days: list[CrewDay] = ctx.blackboard.get("crew_days", [])
        unscheduled: list[str] = ctx.blackboard.get("unscheduled", [])
        conflicts: list[str] = list(ctx.blackboard.get("equipment_conflicts", []))
        for g in ctx.blackboard.get("equipment_gaps", []):
            conflicts.append(
                f"Job {g['job_id']} missing equipment on {g['day']} (crew {g['crew_id']}): {', '.join(g['missing'])}"
            )
        for cd in crew_days:
            for w in cd.warnings:
                conflicts.append(f"{cd.crew_id} {cd.day.isoformat()}: {w}")

        # Pre-return validation: catch overbooked days, orphan stops, and
        # capacity violations so they are surfaced in the plan's conflicts list
        # rather than silently passed to dispatch.
        validation_issues = await self._validate_plan(ctx, crew_days, unscheduled)
        conflicts.extend(validation_issues)

        summary = await self._summarize(ctx, crew_days, unscheduled, conflicts)

        plan = WeekPlan(
            week_start=ws,
            days=crew_days,
            unscheduled_job_ids=unscheduled,
            conflicts=conflicts,
            summary=summary,
        )

        # Per-message quality (from the comms sub-pipeline)
        critic_scores = ctx.blackboard.get("message_critic_scores", {})
        guardrail_flag_list = ctx.blackboard.get("message_guardrail_flags", [])
        flagged_jobs = {f["job_id"]: f["flags"] for f in guardrail_flag_list}
        message_quality: dict[str, MessageQuality] = {}
        for jid, score in critic_scores.items():
            message_quality[jid] = MessageQuality(
                job_id=jid,
                score=score,
                guardrail_passed=jid not in flagged_jobs,
                guardrail_flags=flagged_jobs.get(jid, []),
            )

        # Plan review (from PlanReviewerAgent)
        review_raw = ctx.blackboard.get("plan_review")
        review = PlanReview(**review_raw) if review_raw else None

        result = PlanResult(
            plan=plan,
            events=ctx.events,
            client_messages=ctx.blackboard.get("client_messages", {}),
            message_quality=message_quality,
            review=review,
        )

        # Save draft preview — do NOT change job statuses yet.
        # Jobs remain PENDING until the user explicitly confirms the plan
        # via POST /api/plan/confirm.  This keeps draft and confirmed states
        # cleanly separated: re-running the planner never silently promotes
        # unconfirmed jobs to SCHEDULED.
        store.set_plan(result)
        await ctx.emit(self.name, "done", summary)

        return result

    async def _evict_equipment_conflicts(self, ctx: AgentContext) -> None:
        """Remove jobs with unresolvable equipment conflicts from crew_days and
        promote them into the unscheduled list."""
        bumped_job_ids: set[str] = set(ctx.blackboard.get("equipment_bumped_jobs", []))
        if not bumped_job_ids:
            return

        crew_days: list[CrewDay] = ctx.blackboard.get("crew_days", [])
        cleaned: list[CrewDay] = []
        for cd in crew_days:
            original_len = len(cd.stops)
            cd.stops = [s for s in cd.stops if s.job_id not in bumped_job_ids]
            if cd.stops:
                if len(cd.stops) != original_len:
                    # Recompute work total; drive is an overestimate but safe.
                    cd.total_work_minutes = sum(s.duration_minutes for s in cd.stops)
                    crew_obj = store.get_crew(cd.crew_id)
                    if crew_obj:
                        load = cd.total_work_minutes + cd.total_drive_minutes
                        cd.utilization = round(min(1.0, load / max(1, crew_obj.daily_minutes)), 2)
                        cd.overbooked = load > crew_obj.daily_minutes
                cleaned.append(cd)

        ctx.blackboard["crew_days"] = cleaned

        existing: set[str] = set(ctx.blackboard.get("unscheduled", []))
        ctx.blackboard["unscheduled"] = list(existing | bumped_job_ids)

        await ctx.emit(
            self.name,
            "evict",
            f"Evicted {len(bumped_job_ids)} job(s) with unresolvable equipment conflicts "
            f"to unscheduled: {', '.join(sorted(bumped_job_ids))}.",
        )

    async def _validate_plan(
        self,
        ctx: AgentContext,
        crew_days: list[CrewDay],
        unscheduled: list[str],
    ) -> list[str]:
        """Validate the assembled plan and return a list of conflict descriptions.

        Checks performed:
        - Overbooked crew-days (work + drive > capacity)
        - Stops referencing job IDs not present in the store
        - Jobs from ctx.jobs that are missing from both scheduled and unscheduled lists
        """
        issues: list[str] = []
        jobs_in_ctx = {j.id for j in ctx.jobs}
        scheduled_ids: set[str] = set()

        for cd in crew_days:
            crew_obj = store.get_crew(cd.crew_id)
            cap = crew_obj.daily_minutes if crew_obj else 480

            for stop in cd.stops:
                scheduled_ids.add(stop.job_id)
                # Flag stops that reference a job not in the store.
                if store.get_job(stop.job_id) is None:
                    issues.append(
                        f"Orphan stop: {stop.job_id} on {cd.crew_id}/{cd.day} "
                        "has no backing job record."
                    )

            # Flag overbooked days (TimeBudgetAgent marks them; double-check here).
            if cd.overbooked:
                day_load = cd.total_work_minutes + cd.total_drive_minutes
                issues.append(
                    f"Overbooked: {cd.crew_id} on {cd.day} — "
                    f"{day_load} min vs {cap} min capacity."
                )
                logger.warning(
                    "Overbooked crew-day %s/%s: %d min vs %d min cap",
                    cd.crew_id, cd.day, day_load, cap,
                )

        # Any job from ctx.jobs that is not scheduled or explicitly unscheduled
        # has been silently dropped — surface this as a conflict.
        accounted_for = scheduled_ids | set(unscheduled)
        dropped = jobs_in_ctx - accounted_for
        for jid in sorted(dropped):
            issues.append(f"Dropped: job {jid} was in planning window but missing from schedule output.")
            logger.error("Job %s dropped from plan output silently.", jid)

        if issues:
            await ctx.emit(
                self.name,
                "validation",
                f"Schedule validation found {len(issues)} issue(s).",
                detail={"issues": issues},
            )
        else:
            await ctx.emit(
                self.name,
                "validation",
                "Schedule validation passed — no overbooked days, orphan stops, or dropped jobs.",
            )

        return issues

    async def _summarize(
        self,
        ctx: AgentContext,
        crew_days: list[CrewDay],
        unscheduled: list[str],
        conflicts: list[str],
    ) -> str:
        total_jobs = sum(len(cd.stops) for cd in crew_days)
        total_work = sum(cd.total_work_minutes for cd in crew_days)
        total_drive = sum(cd.total_drive_minutes for cd in crew_days)
        overbooked = sum(1 for cd in crew_days if cd.overbooked)

        bullet_text = (
            f"Scheduled {total_jobs} jobs across {len(crew_days)} crew-days. "
            f"Total work: {total_work} min ({round(total_work/60,1)} h). "
            f"Total drive: {total_drive} min ({round(total_drive/60,1)} h). "
            f"Unscheduled: {len(unscheduled)}. "
            f"Conflicts/warnings: {len(conflicts)}. "
            f"Overbooked crew-days: {overbooked}."
        )

        if llm.enabled:
            sys = (
                "You are an operations supervisor. Summarize a weekly production plan in "
                "3-5 sentences. Be concrete: jobs scheduled, drive vs. work mix, conflicts to "
                "watch, and a specific suggestion if there are unscheduled jobs."
            )
            user = (
                bullet_text
                + "\nConflicts:\n- "
                + "\n- ".join(conflicts[:8])
                + "\nWrite the summary."
            )
            text = await llm.chat(
                sys,
                user,
                max_tokens=260,
                temperature=0.4,
                trace=llm_trace_callback(ctx),
                trace_label="supervisor.summary",
            )
            if text:
                return text
        return bullet_text

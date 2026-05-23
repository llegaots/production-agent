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
        hard_constraints: Optional[list] = None,
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
        if hard_constraints:
            ctx.blackboard["hard_constraints"] = hard_constraints

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

        # Post Phase 2: consolidate under-utilised crew-days (<40%) where
        # same-zone jobs on earlier days exist and can absorb them.
        await self._consolidate_underutilized(ctx)

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

    @staticmethod
    def _resequence_crew_day(crew_day: CrewDay, job_ids: list[str], jobs_by_id: dict, crew) -> None:
        """Recompute stop timing for a crew_day with the given ordered job_ids."""
        from ..models import ScheduledStop
        from .base import haversine_km, drive_minutes

        stops = []
        cur_lat, cur_lng = crew.base_lat, crew.base_lng
        minute_cursor = 0
        total_drive = 0
        total_work = 0

        for idx, jid in enumerate(job_ids):
            job = jobs_by_id.get(jid)
            if not job:
                continue
            d_km = haversine_km(cur_lat, cur_lng, job.lat, job.lng)
            travel = drive_minutes(d_km)
            minute_cursor += travel
            total_drive += travel
            stops.append(
                ScheduledStop(
                    job_id=job.id,
                    order=idx,
                    start_minute=minute_cursor,
                    travel_minutes_before=travel,
                    duration_minutes=job.estimated_minutes,
                )
            )
            minute_cursor += job.estimated_minutes
            total_work += job.estimated_minutes
            cur_lat, cur_lng = job.lat, job.lng

        return_km = haversine_km(cur_lat, cur_lng, crew.base_lat, crew.base_lng)
        return_drive = drive_minutes(return_km)
        total_drive += return_drive

        day_load = minute_cursor + return_drive
        crew_day.stops = stops
        crew_day.total_work_minutes = total_work
        crew_day.total_drive_minutes = total_drive
        crew_day.utilization = round(min(1.0, day_load / max(1, crew.daily_minutes)), 2)
        crew_day.overbooked = day_load > crew.daily_minutes

    async def _consolidate_underutilized(self, ctx: AgentContext) -> None:
        """Merge under-utilised crew-days (<40%) into earlier same-zone days.

        For each crew-day below the 40% threshold, check if all its jobs are
        geographically close (within 5 km) to jobs on an earlier day of the
        same week.  When a suitable earlier day exists with enough remaining
        capacity, move the jobs there and remove the thin crew-day.

        Hard constraints are respected: jobs that appear in the hard_constraints
        blackboard are never moved by this pass.
        """
        from .base import haversine_km, drive_minutes

        crew_days: list[CrewDay] = ctx.blackboard.get("crew_days", [])
        if not crew_days:
            return

        jobs_by_id = {j.id: j for j in ctx.jobs}
        crews_by_id = {c.id: c for c in ctx.crews}

        # Build set of job IDs locked by hard constraints.
        locked_ids: set[str] = set()
        for hc in ctx.blackboard.get("hard_constraints", []):
            locked_ids.update(hc.job_ids)

        UTIL_THRESHOLD = 0.40
        GEO_PROXIMITY_KM = 5.0

        # Sort crew_days by (day, crew) so earlier days come first.
        sorted_days = sorted(crew_days, key=lambda cd: (cd.day, cd.crew_id))

        removed: set[int] = set()  # indices into sorted_days to remove

        for i, thin_cd in enumerate(sorted_days):
            if i in removed:
                continue
            if thin_cd.utilization >= UTIL_THRESHOLD:
                continue
            # Skip if any job in this crew-day is locked.
            thin_job_ids = [s.job_id for s in thin_cd.stops]
            if any(jid in locked_ids for jid in thin_job_ids):
                continue
            if not thin_job_ids:
                continue

            thin_jobs = [jobs_by_id[jid] for jid in thin_job_ids if jid in jobs_by_id]
            if not thin_jobs:
                continue

            thin_crew = crews_by_id.get(thin_cd.crew_id)
            if not thin_crew:
                continue

            # Look for an earlier crew-day (any crew) that:
            #   (a) precedes this day in the week
            #   (b) has enough remaining capacity for these jobs + drive overhead
            #   (c) already has jobs geographically close to all thin-day jobs
            for j, early_cd in enumerate(sorted_days):
                if j in removed or j == i:
                    continue
                if early_cd.day >= thin_cd.day:
                    continue  # must be an earlier day

                early_crew = crews_by_id.get(early_cd.crew_id)
                if not early_crew:
                    continue

                early_job_ids = [s.job_id for s in early_cd.stops]
                early_jobs = [jobs_by_id[jid] for jid in early_job_ids if jid in jobs_by_id]
                if not early_jobs:
                    continue

                # Check if all thin-day jobs are within geo_proximity of early-day centroid.
                early_lat = sum(j2.lat for j2 in early_jobs) / len(early_jobs)
                early_lng = sum(j2.lng for j2 in early_jobs) / len(early_jobs)
                if any(
                    haversine_km(early_lat, early_lng, tj.lat, tj.lng) > GEO_PROXIMITY_KM
                    for tj in thin_jobs
                ):
                    continue  # not in the same zone

                # Check capacity: early day must fit the additional work + rough drive.
                extra_work = sum(tj.estimated_minutes for tj in thin_jobs)
                drive_overhead = 15 * len(thin_jobs)
                current_load = early_cd.total_work_minutes + early_cd.total_drive_minutes
                if current_load + extra_work + drive_overhead > early_crew.daily_minutes:
                    continue  # would overbook

                # Check date windows for all thin jobs on the early day.
                if any(
                    tj.earliest_date > early_cd.day or tj.latest_date < early_cd.day
                    for tj in thin_jobs
                ):
                    continue

                # Verify the early crew has all required skills and equipment
                # for the jobs being moved.
                from ..storage import store as _store
                early_skills = set(early_crew.skills)
                early_equip: set = set()
                for eid in early_crew.equipment_ids:
                    eq = _store.get_equipment(eid)
                    if eq:
                        early_equip.add(eq.kind)
                required_skills = {s for tj in thin_jobs for s in tj.required_skills}
                required_equip = {e for tj in thin_jobs for e in tj.required_equipment}
                if not required_skills.issubset(early_skills):
                    continue
                if not required_equip.issubset(early_equip):
                    continue

                # Consolidate: move stops from thin_cd to early_cd.
                # Append and renumber stops, then recalculate all timing so
                # no start_minute overlaps occur.
                combined_job_ids = [s.job_id for s in early_cd.stops] + [
                    s.job_id for s in thin_cd.stops
                ]
                self._resequence_crew_day(early_cd, combined_job_ids, jobs_by_id, early_crew)

                removed.add(i)
                await ctx.emit(
                    self.name,
                    "consolidate",
                    f"Consolidated under-utilised {thin_cd.crew_id} {thin_cd.day.isoformat()} "
                    f"({int(thin_cd.utilization * 100)}% util) into "
                    f"{early_cd.crew_id} {early_cd.day.isoformat()} — "
                    f"same-zone jobs, {len(thin_jobs)} stop(s) moved.",
                    detail={
                        "from_crew_id": thin_cd.crew_id,
                        "from_day": thin_cd.day.isoformat(),
                        "to_crew_id": early_cd.crew_id,
                        "to_day": early_cd.day.isoformat(),
                        "moved_job_ids": thin_job_ids,
                    },
                )
                break  # one consolidation target per thin day

        if removed:
            ctx.blackboard["crew_days"] = [
                cd for k, cd in enumerate(sorted_days) if k not in removed
            ]

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

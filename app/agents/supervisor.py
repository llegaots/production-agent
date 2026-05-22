"""SupervisorAgent - orchestrates the multi-agent weekly plan."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from ..llm import llm
from ..models import CrewDay, PlanResult, WeekPlan
from ..storage import store
from .base import Agent, AgentContext, EventEmitter
from .client_comms import ClientCommsAgent
from .crew_match import CrewMatchAgent
from .equipment import EquipmentAgent
from .geo_cluster import GeoClusterAgent
from .time_budget import TimeBudgetAgent


def _next_monday(today: Optional[date] = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())


class SupervisorAgent(Agent):
    """Runs the full pipeline and assembles a ``PlanResult``."""

    name = "SupervisorAgent"

    def __init__(self) -> None:
        self.geo = GeoClusterAgent()
        self.crew = CrewMatchAgent()
        self.equipment = EquipmentAgent()
        self.budget = TimeBudgetAgent()
        self.comms = ClientCommsAgent()

    async def plan_week(
        self,
        week_start: Optional[date] = None,
        emitter: Optional[EventEmitter] = None,
    ) -> PlanResult:
        ws = week_start or _next_monday()
        jobs = [j for j in store.list_jobs() if j.status.value in ("pending", "scheduled", "rescheduled")]
        crews = store.list_crews()

        ctx = AgentContext(week_start=ws, crews=crews, jobs=jobs, emitter=emitter)

        await ctx.emit(self.name, "start", f"Planning week starting {ws.isoformat()} with {len(jobs)} jobs across {len(crews)} crews.")

        await self.geo.run(ctx)
        await self.crew.run(ctx)
        await self.equipment.run(ctx)
        await self.budget.run(ctx)
        await self.comms.run(ctx)

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
        result = PlanResult(
            plan=plan,
            events=ctx.events,
            client_messages=ctx.blackboard.get("client_messages", {}),
        )

        # Persist & mark scheduled jobs
        from ..models import JobStatus
        for cd in crew_days:
            for s in cd.stops:
                store.set_job_status(s.job_id, JobStatus.SCHEDULED)
        store.set_plan(result)
        await ctx.emit(self.name, "done", summary)

        return result

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
            text = await llm.chat(sys, user, max_tokens=260, temperature=0.4)
            if text:
                return text
        return bullet_text

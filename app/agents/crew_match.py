"""CrewMatchAgent - assigns crews & days to geographic clusters.

Anthropic pattern: **Workflow step (router + scorer)**.

For each cluster the agent first applies *hard filters* (the crew must
have every required skill and every required equipment kind) and then
scores the remaining (crew, day) pairs on soft signals (skill overlap,
specialty fit, headroom for load-balancing). The highest-scoring slot
wins.

It produces a preliminary ``draft_plan`` on the blackboard, a list of
``{crew_id, day, job_ids}`` tuples. Subsequent agents validate equipment
and time budgets and may push jobs back into ``unscheduled``.
"""
from __future__ import annotations

import logging
from datetime import date

from ..models import Crew, EquipmentKind, Job
from ..scheduling_prefs import SchedulingMode, cluster_sort_key, placement_score_bonus
from ..storage import store
from .base import Agent, AgentContext, drive_minutes, haversine_km, week_days

logger = logging.getLogger(__name__)


class CrewMatchAgent(Agent):
    name = "CrewMatchAgent"

    @staticmethod
    def _crew_covers_skills(crew: Crew, jobs: list[Job]) -> bool:
        required = {s for j in jobs for s in j.required_skills}
        return required.issubset(set(crew.skills))

    @staticmethod
    def _crew_covers_equipment(crew: Crew, jobs: list[Job], equipment_kinds_by_crew: dict[str, set]) -> bool:
        required = {e for j in jobs for e in j.required_equipment}
        return required.issubset(equipment_kinds_by_crew.get(crew.id, set()))

    @staticmethod
    def _score_crew_for_cluster(crew: Crew, jobs: list[Job]) -> float:
        required_skills = {s for j in jobs for s in j.required_skills}
        skill_overlap = len(required_skills.intersection(set(crew.skills)))
        skill_gap = len(required_skills - set(crew.skills))
        avg_difficulty = sum(j.difficulty for j in jobs) / max(1, len(jobs))
        crew_difficulty_capacity = 1 + len(crew.skills)

        score = 0.0
        score += skill_overlap * 3.0
        score -= skill_gap * 50.0  # very strong penalty - skills are mandatory
        score += min(0.0, crew_difficulty_capacity - avg_difficulty) * 0.5
        # Specialty bonus: prefer cheaper crews for low-difficulty work, and
        # expensive specialty crews for high-difficulty work.
        if avg_difficulty <= 2 and crew.hourly_cost <= 130:
            score += 2.0
        if avg_difficulty >= 4 and crew.hourly_cost >= 180:
            score += 2.0
        return score

    @staticmethod
    def _ordered_for_route(crew: Crew, jobs: list[Job]) -> list[Job]:
        """Greedy nearest-neighbor from the crew's base."""
        remaining = jobs[:]
        ordered: list[Job] = []
        cur_lat, cur_lng = crew.base_lat, crew.base_lng
        while remaining:
            nxt = min(remaining, key=lambda j: haversine_km(cur_lat, cur_lng, j.lat, j.lng))
            ordered.append(nxt)
            cur_lat, cur_lng = nxt.lat, nxt.lng
            remaining.remove(nxt)
        return ordered

    async def run(self, ctx: AgentContext) -> None:
        clusters: list[dict] = ctx.blackboard.get("geo_clusters", [])
        jobs_by_id = {j.id: j for j in ctx.jobs}
        days = week_days(ctx.week_start)
        await ctx.emit_tool(
            "crew_match",
            "invoke",
            f"Assigning {len(clusters)} geo clusters to crews/days (skill + equipment constraints).",
            {"clusters": len(clusters), "crews": len(ctx.crews), "days": len(days)},
        )
        await ctx.emit(
            self.name,
            "start",
            f"Matching {len(clusters)} clusters across {len(ctx.crews)} crews over {len(days)} working days.",
        )

        # Pre-compute equipment kinds per crew once
        crew_equipment_kinds: dict[str, set[EquipmentKind]] = {}
        for c in ctx.crews:
            kinds: set[EquipmentKind] = set()
            for eid in c.equipment_ids:
                e = store.get_equipment(eid)
                if e:
                    kinds.add(e.kind)
            crew_equipment_kinds[c.id] = kinds

        mode: SchedulingMode = ctx.blackboard.get("scheduling_mode", ctx.scheduling_mode)
        used: dict[tuple[str, date], int] = {}
        draft_plan: list[dict] = []
        unscheduled: list[str] = []

        # Sort clusters: default heaviest-first; REVENUE_PRIORITY sorts by price.
        order = sorted(
            range(len(clusters)),
            key=lambda i: -cluster_sort_key(mode, clusters[i]["job_ids"], jobs_by_id),
        )

        def _estimate_drive_budget(crew: Crew, jobs: list[Job]) -> int:
            """Estimate total drive time for this crew serving these jobs.

            Uses haversine from base → first job → between stops → back to base.
            This is the same approach as TimeBudgetAgent, so capacity checks here
            align with what the final schedule actually produces, preventing
            crew-days from being overbooked after TimeBudgetAgent runs.
            """
            if not jobs:
                return 0
            ordered = self._ordered_for_route(crew, jobs)
            total_km = 0.0
            cur_lat, cur_lng = crew.base_lat, crew.base_lng
            for j in ordered:
                total_km += haversine_km(cur_lat, cur_lng, j.lat, j.lng)
                cur_lat, cur_lng = j.lat, j.lng
            # Return to base
            total_km += haversine_km(cur_lat, cur_lng, crew.base_lat, crew.base_lng)
            return drive_minutes(total_km)

        def place(jobs: list[Job], emit_phase: str) -> bool:
            """Place a contiguous batch of jobs on the best (crew, day) slot.

            Returns True if placed (all jobs together), False otherwise.
            """
            total = sum(j.estimated_minutes for j in jobs)
            # Hard-filter crews by skills + equipment
            eligible = [
                c
                for c in ctx.crews
                if self._crew_covers_skills(c, jobs)
                and self._crew_covers_equipment(c, jobs, crew_equipment_kinds)
            ]
            if not eligible:
                logger.debug(
                    "No eligible crew for jobs %s (skills: %s, equipment: %s)",
                    [j.id for j in jobs],
                    [s.value for j in jobs for s in j.required_skills],
                    [e.value for j in jobs for e in j.required_equipment],
                )
                return False

            avg_drive_km = sum(
                haversine_km(crew.base_lat, crew.base_lng, j.lat, j.lng)
                for crew in eligible
                for j in jobs
            ) / max(1, len(eligible) * len(jobs))

            candidates: list[tuple[float, Crew, date]] = []
            for crew in eligible:
                fit = self._score_crew_for_cluster(crew, jobs)
                crew_drive = sum(haversine_km(crew.base_lat, crew.base_lng, j.lat, j.lng) for j in jobs) / max(
                    1, len(jobs)
                )
                # Use per-crew realistic drive estimate so capacity checks match
                # TimeBudgetAgent output and crew-days don't end up overbooked.
                drive_budget = _estimate_drive_budget(crew, jobs)
                for day in days:
                    # Respect each job's date window: the day must fall within
                    # every job's [earliest_date, latest_date] range.
                    if any(day < j.earliest_date or day > j.latest_date for j in jobs):
                        continue
                    used_min = used.get((crew.id, day), 0)
                    if used_min + total + drive_budget > crew.daily_minutes:
                        continue
                    remaining = crew.daily_minutes - used_min
                    score = fit + placement_score_bonus(mode, remaining, crew_drive or avg_drive_km)
                    candidates.append((score, crew, day))

            if not candidates:
                return False

            candidates.sort(key=lambda t: -t[0])
            _, crew, day = candidates[0]

            ordered_jobs = self._ordered_for_route(crew, jobs)
            drive_budget = _estimate_drive_budget(crew, ordered_jobs)
            draft_plan.append(
                {"crew_id": crew.id, "day": day, "job_ids": [j.id for j in ordered_jobs]}
            )
            # Track work + estimated drive so subsequent placements respect the
            # realistic day load and capacity is not exceeded.
            used[(crew.id, day)] = used.get((crew.id, day), 0) + total + drive_budget
            logger.debug(
                "Placed %s jobs on %s/%s: work=%d drive_est=%d used=%d cap=%d",
                len(jobs), crew.id, day, total, drive_budget,
                used[(crew.id, day)], crew.daily_minutes,
            )
            return True

        for idx in order:
            cluster = clusters[idx]
            cluster_jobs = [jobs_by_id[j] for j in cluster["job_ids"]]
            total_minutes = sum(j.estimated_minutes for j in cluster_jobs)

            if place(cluster_jobs, "assign"):
                last = draft_plan[-1]
                crew_name = next(c.name for c in ctx.crews if c.id == last["crew_id"])
                await ctx.emit(
                    self.name,
                    "assign",
                    f"Cluster of {len(cluster_jobs)} jobs ({total_minutes} min) -> {crew_name} on {last['day'].isoformat()}.",
                    detail={
                        "crew_id": last["crew_id"],
                        "day": last["day"].isoformat(),
                        "job_ids": last["job_ids"],
                        "skill_match": list({s.value for j in cluster_jobs for s in j.required_skills}),
                    },
                )
                continue

            # Cluster didn't fit as a unit. Split it and place each job individually.
            await ctx.emit(
                self.name,
                "split",
                f"Splitting cluster of {len(cluster_jobs)} jobs ({total_minutes} min) — no single crew/day fits.",
            )
            for j in sorted(cluster_jobs, key=lambda x: -x.estimated_minutes):
                if place([j], "single"):
                    last = draft_plan[-1]
                    crew_name = next(c.name for c in ctx.crews if c.id == last["crew_id"])
                    await ctx.emit(
                        self.name,
                        "single",
                        f"Placed split job {j.id} ({j.estimated_minutes}m, diff {j.difficulty}) -> {crew_name} on {last['day'].isoformat()}.",
                    )
                else:
                    unscheduled.append(j.id)
                    await ctx.emit(
                        self.name,
                        "warn",
                        f"Could not place job {j.id} this week (skills/equipment/capacity).",
                    )

        # Merge multiple draft entries for the same crew/day
        merged: dict[tuple[str, date], list[str]] = {}
        for entry in draft_plan:
            key = (entry["crew_id"], entry["day"])
            merged.setdefault(key, []).extend(entry["job_ids"])

        # Safety invariant: every job in ctx.jobs must appear in either the
        # draft plan or the unscheduled list.  Jobs that are silently dropped
        # (e.g. due to an exception in placement logic) are caught here and
        # added to unscheduled so the caller can always account for them.
        placed_ids: set[str] = {jid for jids in merged.values() for jid in jids}
        unscheduled_set: set[str] = set(unscheduled)
        for job in ctx.jobs:
            if job.id not in placed_ids and job.id not in unscheduled_set:
                unscheduled.append(job.id)
                unscheduled_set.add(job.id)
                await ctx.emit(
                    self.name,
                    "warn",
                    f"Job {job.id} was not placed or deferred — adding to unscheduled "
                    f"(required skills: {[s.value for s in job.required_skills]}).",
                )

        ctx.blackboard["draft_plan"] = [
            {"crew_id": k[0], "day": k[1], "job_ids": v} for k, v in merged.items()
        ]
        ctx.blackboard["unscheduled"] = unscheduled
        await ctx.emit(
            self.name,
            "done",
            f"Drafted {len(merged)} crew-days; {len(unscheduled)} jobs deferred.",
        )

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

from datetime import date

from ..models import Crew, EquipmentKind, Job
from ..scheduling_prefs import (
    SchedulingMode,
    cluster_sort_key,
    load_balance_bonus,
    placement_score_bonus,
    week_fill_bonus,
)
from ..storage import store
from .base import Agent, AgentContext, haversine_km, week_days


def _fleet_quantity(kind: EquipmentKind) -> int:
    return sum(eq.quantity for eq in store.list_equipment() if eq.kind == kind)


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

    @staticmethod
    def _crews_active_on_day(
        slots: dict[tuple[str, date], list[str] | int],
        day: date,
        crew_equipment_kinds: dict[str, set[EquipmentKind]],
        *,
        kind: EquipmentKind | None = None,
    ) -> int:
        """Count crews with work (or reserved minutes) on ``day``."""
        seen: set[str] = set()
        for (crew_id, d), val in slots.items():
            if d != day:
                continue
            active = (isinstance(val, int) and val > 0) or (isinstance(val, list) and val)
            if not active:
                continue
            if kind is None or kind in crew_equipment_kinds.get(crew_id, set()):
                seen.add(crew_id)
        return len(seen)

    @classmethod
    def _fleet_blocks_new_crew_on_day(
        cls,
        slots: dict[tuple[str, date], list[str] | int],
        crew_id: str,
        day: date,
        crew_equipment_kinds: dict[str, set[EquipmentKind]],
    ) -> bool:
        """True when turning on ``crew_id`` on ``day`` would exceed fleet equipment."""
        already = (
            (isinstance(slots.get((crew_id, day)), int) and slots.get((crew_id, day), 0) > 0)
            or bool(slots.get((crew_id, day)))
        )
        if already:
            return False
        for eq_kind in crew_equipment_kinds.get(crew_id, set()):
            fleet = _fleet_quantity(eq_kind)
            in_use = cls._crews_active_on_day(slots, day, crew_equipment_kinds, kind=eq_kind)
            if in_use >= fleet:
                return True
        return False

    def _rebalance_balanced_draft(
        self,
        ctx: AgentContext,
        merged: dict[tuple[str, date], list[str]],
        jobs_by_id: dict[str, Job],
        crew_equipment_kinds: dict[str, set[EquipmentKind]],
        *,
        max_spread_minutes: int = 150,
    ) -> dict[tuple[str, date], list[str]]:
        """Move jobs from overloaded crew-days to underloaded ones (BALANCED mode)."""
        crews_by_id = {c.id: c for c in ctx.crews}
        crew_ids = [c.id for c in ctx.crews]
        days = week_days(ctx.week_start)
        out = {k: list(v) for k, v in merged.items()}
        before_count = sum(len(v) for v in out.values())

        def work_minutes(crew_id: str, day: date) -> int:
            return sum(
                jobs_by_id[jid].estimated_minutes
                for jid in out.get((crew_id, day), [])
                if jid in jobs_by_id
            )

        def can_host(job: Job, crew_id: str, day: date) -> bool:
            crew = crews_by_id[crew_id]
            if day < job.earliest_date or day > job.latest_date:
                return False
            if not self._crew_covers_skills(crew, [job]):
                return False
            if not self._crew_covers_equipment(crew, [job], crew_equipment_kinds):
                return False
            if self._fleet_blocks_new_crew_on_day(out, crew_id, day, crew_equipment_kinds):
                return False
            load = work_minutes(crew_id, day) + job.estimated_minutes + 30
            return load <= crew.daily_minutes

        def remove_job(src_key: tuple[str, date], jid: str) -> None:
            current = list(out.get(src_key, []))
            if jid not in current:
                return
            out[src_key] = [j for j in current if j != jid]
            if not out[src_key]:
                del out[src_key]

        def add_job(tgt_key: tuple[str, date], jid: str) -> None:
            out.setdefault(tgt_key, []).append(jid)

        max_iters = max(1, len(jobs_by_id) * len(days) * len(crew_ids))
        for _ in range(max_iters):
            improved = False
            for day in days:
                loads = {cid: work_minutes(cid, day) for cid in crew_ids}
                if max(loads.values()) - min(loads.values()) <= max_spread_minutes:
                    continue
                overloaded = max(crew_ids, key=lambda cid: loads[cid])
                src_key = (overloaded, day)
                src_jobs = list(out.get(src_key, []))
                if not src_jobs:
                    continue
                for jid in sorted(
                    src_jobs,
                    key=lambda j: jobs_by_id[j].estimated_minutes if j in jobs_by_id else 0,
                ):
                    job = jobs_by_id.get(jid)
                    if not job:
                        continue
                    # Same-day cross-crew move (preferred).
                    same_day_targets = [
                        cid
                        for cid in crew_ids
                        if cid != overloaded and can_host(job, cid, day)
                    ]
                    if same_day_targets:
                        target = min(same_day_targets, key=lambda cid: loads[cid])
                        remove_job(src_key, jid)
                        add_job((target, day), jid)
                        improved = True
                        break
                    # Cross-day: same crew or different crew with slack (prefer earlier days).
                    alt_targets: list[tuple[int, int, str, date]] = []
                    for cid in crew_ids:
                        for alt_day in days:
                            if alt_day == day and cid == overloaded:
                                continue
                            if not can_host(job, cid, alt_day):
                                continue
                            alt_targets.append(
                                (work_minutes(cid, alt_day), alt_day.toordinal(), cid, alt_day)
                            )
                    if not alt_targets:
                        continue
                    _, _, target_crew, target_day = min(alt_targets)
                    remove_job(src_key, jid)
                    add_job((target_crew, target_day), jid)
                    improved = True
                    break
            if not improved:
                break

        after_count = sum(len(v) for v in out.values())
        if after_count != before_count:
            return merged
        return out

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
                return False

            # Reserve a rough drive budget: 20 min round-trip to area + 15 min
            # between stops. The TimeBudgetAgent computes the real number; this
            # is just enough headroom that we don't overbook by a wide margin.
            drive_budget = 20 + 15 * max(0, len(jobs) - 1)

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
                for day in days:
                    # Respect each job's date window: the day must fall within
                    # every job's [earliest_date, latest_date] range.
                    if any(day < j.earliest_date or day > j.latest_date for j in jobs):
                        continue
                    used_min = used.get((crew.id, day), 0)
                    if used_min + total + drive_budget > crew.daily_minutes:
                        continue
                    if self._fleet_blocks_new_crew_on_day(used, crew.id, day, crew_equipment_kinds):
                        continue
                    remaining = crew.daily_minutes - used_min
                    day_loads = [used.get((c.id, day), 0) for c in eligible]
                    score = (
                        fit
                        + placement_score_bonus(mode, remaining, crew_drive or avg_drive_km)
                        + load_balance_bonus(mode, used_min, day_loads)
                        + week_fill_bonus(ctx.week_start, day)
                    )
                    candidates.append((score, crew, day))

            if not candidates:
                return False

            candidates.sort(key=lambda t: -t[0])
            _, crew, day = candidates[0]

            ordered_jobs = self._ordered_for_route(crew, jobs)
            draft_plan.append(
                {"crew_id": crew.id, "day": day, "job_ids": [j.id for j in ordered_jobs]}
            )
            used[(crew.id, day)] = used.get((crew.id, day), 0) + total
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

        if mode == SchedulingMode.BALANCED and merged:
            merged = self._rebalance_balanced_draft(
                ctx, merged, jobs_by_id, crew_equipment_kinds
            )
            await ctx.emit(
                self.name,
                "rebalance",
                "Applied cross-crew load balancing for BALANCED mode.",
            )

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

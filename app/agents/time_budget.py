"""TimeBudgetAgent - sequences jobs in each crew/day and validates time fit.

Anthropic pattern: **Parallelization (sectioning)**.

Runs concurrently with EquipmentAgent. Produces ``CrewDay`` records with
ordered ``ScheduledStop`` entries that include travel time between stops.
Flags overbooked days and per-day warnings (e.g., "after-hours storefront
job is scheduled at 9am").
"""
from __future__ import annotations

from datetime import date

from ..models import CrewDay, Job, ScheduledStop
from .base import Agent, AgentContext, drive_minutes, haversine_km


class TimeBudgetAgent(Agent):
    name = "TimeBudgetAgent"

    @staticmethod
    def _reorder_if_backtrack(job_objs: list[Job], crew) -> list[Job]:
        """Detect route backtracks and fix via nearest-neighbour from depot.

        A backtrack occurs when the distance from stop[N] to stop[N+1] exceeds
        the distance from stop[N] back to the depot — meaning the route moves
        further away when it could return. When detected, re-sequence via
        greedy nearest-neighbour from the crew base.
        """
        if len(job_objs) < 2:
            return job_objs

        has_backtrack = False
        prev_lat, prev_lng = crew.base_lat, crew.base_lng
        for n, job in enumerate(job_objs):
            if n == 0:
                prev_lat, prev_lng = job.lat, job.lng
                continue
            d_to_next = haversine_km(prev_lat, prev_lng, job.lat, job.lng)
            d_to_depot = haversine_km(prev_lat, prev_lng, crew.base_lat, crew.base_lng)
            if d_to_next > d_to_depot:
                has_backtrack = True
                break
            prev_lat, prev_lng = job.lat, job.lng

        if not has_backtrack:
            return job_objs

        # Re-sequence with greedy nearest-neighbour from depot.
        remaining = job_objs[:]
        reordered: list[Job] = []
        cur_lat, cur_lng = crew.base_lat, crew.base_lng
        while remaining:
            nxt = min(remaining, key=lambda j: haversine_km(cur_lat, cur_lng, j.lat, j.lng))
            reordered.append(nxt)
            cur_lat, cur_lng = nxt.lat, nxt.lng
            remaining.remove(nxt)
        return reordered

    async def run(self, ctx: AgentContext) -> None:
        draft = ctx.blackboard.get("draft_plan", [])
        jobs_by_id = {j.id: j for j in ctx.jobs}
        crews_by_id = {c.id: c for c in ctx.crews}

        await ctx.emit_tool(
            "time_budget",
            "invoke",
            "Sequencing stops with drive-time estimates and daily minute caps.",
            {"draft_entries": len(draft)},
        )
        await ctx.emit(self.name, "start", "Sequencing stops & validating time budgets.")

        crew_days: list[CrewDay] = []
        any_overbook = 0

        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            day: date = entry["day"]
            job_objs: list[Job] = [jobs_by_id[j] for j in entry["job_ids"]]

            # ── Route backtrack detection & correction ────────────────────────
            # After sequencing stops, detect when stop[N+1] is farther from
            # stop[N] than stop[N] is from the depot.  Re-order with
            # nearest-neighbour from depot when a backtrack is found.
            job_objs = self._reorder_if_backtrack(job_objs, crew)

            stops: list[ScheduledStop] = []
            cur_lat, cur_lng = crew.base_lat, crew.base_lng
            minute_cursor = 0
            total_drive = 0
            total_work = 0
            warnings: list[str] = []

            for idx, job in enumerate(job_objs):
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

                # Sniff for hard time-of-day constraints in the notes.
                lower = job.notes.lower() if job.notes else ""
                if "before" in lower and "open" in lower and idx > 0:
                    warnings.append(
                        f"Job {job.id} has a 'before open' note but is scheduled at slot {idx + 1}."
                    )
                if "after-hours" in lower and idx == 0:
                    warnings.append(
                        f"Job {job.id} is an after-hours job; consider scheduling later in the shift."
                    )

            # ── Backtrack warning on final sequence ───────────────────────────
            # Flag any stop where the distance from the previous stop to this
            # stop exceeds the distance from the previous stop back to the depot
            # (indicates a route that goes too far out before returning).
            if len(job_objs) >= 2:
                prev_lat, prev_lng = crew.base_lat, crew.base_lng
                for n, job in enumerate(job_objs):
                    if n == 0:
                        prev_lat, prev_lng = job.lat, job.lng
                        continue
                    d_prev_to_cur = haversine_km(prev_lat, prev_lng, job.lat, job.lng)
                    d_prev_to_depot = haversine_km(prev_lat, prev_lng, crew.base_lat, crew.base_lng)
                    if d_prev_to_cur > d_prev_to_depot:
                        warnings.append(
                            f"Route backtrack at stop {n + 1} ({job.id}): "
                            f"{d_prev_to_cur:.1f} km forward vs {d_prev_to_depot:.1f} km to depot — "
                            f"consider reordering or splitting this crew-day."
                        )
                    prev_lat, prev_lng = job.lat, job.lng

            # return-to-base drive
            return_km = haversine_km(cur_lat, cur_lng, crew.base_lat, crew.base_lng)
            return_drive = drive_minutes(return_km)
            total_drive += return_drive

            day_load = minute_cursor + return_drive
            overbooked = day_load > crew.daily_minutes
            if overbooked:
                any_overbook += 1
                warnings.append(
                    f"Day load is {day_load} min vs crew capacity {crew.daily_minutes} min."
                )

            utilization = round(min(1.0, day_load / max(1, crew.daily_minutes)), 2)
            cd = CrewDay(
                crew_id=crew.id,
                day=day,
                stops=stops,
                total_drive_minutes=total_drive,
                total_work_minutes=total_work,
                utilization=utilization,
                overbooked=overbooked,
                warnings=warnings,
            )
            crew_days.append(cd)

            await ctx.emit(
                self.name,
                "day_built",
                f"{crew.name} {day.isoformat()}: {total_work} min work + {total_drive} min drive (util {int(utilization * 100)}%).",
                detail={
                    "crew_id": crew.id,
                    "day": day.isoformat(),
                    "overbooked": overbooked,
                    "warnings": warnings,
                    "utilization": utilization,
                },
            )

        ctx.blackboard["crew_days"] = crew_days
        await ctx.emit(
            self.name,
            "done",
            f"Built {len(crew_days)} crew-days; {any_overbook} overbooked.",
        )

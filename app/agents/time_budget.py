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

    async def run(self, ctx: AgentContext) -> None:
        draft = ctx.blackboard.get("draft_plan", [])
        jobs_by_id = {j.id: j for j in ctx.jobs}
        crews_by_id = {c.id: c for c in ctx.crews}

        await ctx.emit(self.name, "start", "Sequencing stops & validating time budgets.")

        crew_days: list[CrewDay] = []
        any_overbook = 0

        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            day: date = entry["day"]
            job_objs: list[Job] = [jobs_by_id[j] for j in entry["job_ids"]]

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

"""ReschedulerAgent - handles disruption to an already-planned week.

A reschedule run is triggered by:
  - weather day off
  - equipment failure
  - client cancellation / unavailability
  - crew callout

The agent picks the next-best slot for the affected job using the same
constraints the original planner used, then drafts an explanatory
message to the client.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from ..llm import llm
from ..models import (
    AgentEvent,
    CrewDay,
    Job,
    PlanResult,
    RescheduleResult,
    ScheduledStop,
)
from ..storage import store
from .base import Agent, drive_minutes, haversine_km


class ReschedulerAgent(Agent):
    name = "ReschedulerAgent"

    async def run_reschedule(
        self,
        plan: PlanResult,
        job_id: str,
        reason: str,
        emitter=None,
    ) -> RescheduleResult:
        events: list[AgentEvent] = []

        async def emit(phase: str, message: str, detail: dict | None = None) -> None:
            evt = AgentEvent(agent=self.name, phase=phase, message=message, detail=detail)
            events.append(evt)
            if emitter:
                await emitter(evt)

        job = store.get_job(job_id)
        if not job:
            await emit("error", f"Unknown job {job_id}.")
            return RescheduleResult(job_id=job_id, succeeded=False, events=events)

        await emit("start", f"Replanning job {job_id}: {reason}.")

        # 1) remove the job from its current crew/day
        original_day: Optional[date] = None
        original_crew: Optional[str] = None
        for cd in plan.plan.days:
            for s in list(cd.stops):
                if s.job_id == job_id:
                    original_day = cd.day
                    original_crew = cd.crew_id
                    cd.stops.remove(s)
                    await emit(
                        "remove",
                        f"Removed {job_id} from {cd.crew_id} on {cd.day.isoformat()}.",
                    )
        if original_day:
            await self._resequence_day(plan, original_day, original_crew or "")

        # 2) find the next slot that fits, ranked by:
        #    - day proximity to original (sooner is better)
        #    - crew skill+equipment fit
        #    - remaining capacity
        crews_by_id = {c.id: c for c in store.list_crews()}
        candidate_days: list[date] = []
        # build candidates: original_day+1, original_day+2, ... within latest_date
        start = original_day or job.earliest_date
        d = start
        while d <= job.latest_date:
            d = d + timedelta(days=1)
            if d.weekday() < 5:  # Mon-Fri
                candidate_days.append(d)
        # fall back to days within latest, even before original
        d = job.earliest_date
        while d < start:
            if d.weekday() < 5 and d not in candidate_days:
                candidate_days.append(d)
            d = d + timedelta(days=1)

        best = None
        for day in candidate_days:
            for crew in store.list_crews():
                # skill + equipment fit
                if set(job.required_skills) - set(crew.skills):
                    continue
                crew_kinds = set()
                for eid in crew.equipment_ids:
                    e = store.get_equipment(eid)
                    if e:
                        crew_kinds.add(e.kind)
                if set(job.required_equipment) - crew_kinds:
                    continue

                # capacity check
                day_record = next(
                    (cd for cd in plan.plan.days if cd.crew_id == crew.id and cd.day == day),
                    None,
                )
                used = day_record.total_work_minutes + day_record.total_drive_minutes if day_record else 0
                if used + job.estimated_minutes + 30 <= crew.daily_minutes:
                    best = (day, crew.id, day_record)
                    break
            if best:
                break

        if not best:
            await emit("fail", f"No valid slot found for {job_id} within window.")
            client_msg = self._fallback_client_message(job, success=False)
            return RescheduleResult(
                job_id=job_id, succeeded=False, client_message=client_msg, events=events
            )

        new_day, new_crew_id, day_record = best
        crew = crews_by_id[new_crew_id]

        # 3) insert the job at the end of that crew/day, then resequence
        if day_record is None:
            day_record = CrewDay(crew_id=new_crew_id, day=new_day)
            plan.plan.days.append(day_record)

        day_record.stops.append(
            ScheduledStop(
                job_id=job.id,
                order=len(day_record.stops),
                start_minute=0,  # resequence will recalculate
                travel_minutes_before=0,
                duration_minutes=job.estimated_minutes,
            )
        )
        await self._resequence_day(plan, new_day, new_crew_id)
        await emit(
            "place",
            f"Placed {job_id} with {crew.name} on {new_day.isoformat()}.",
            detail={"new_day": new_day.isoformat(), "new_crew_id": new_crew_id},
        )

        # 4) draft a client message
        client = store.get_client(job.client_id)
        msg = await self._draft_message(job, new_day, crew.name, reason, client)

        plan.client_messages[job.id] = msg
        plan.events.extend(events)
        store.set_plan(plan)

        return RescheduleResult(
            job_id=job_id,
            succeeded=True,
            new_day=new_day,
            new_crew_id=new_crew_id,
            client_message=msg,
            events=events,
        )

    @staticmethod
    async def _resequence_day(plan: PlanResult, day: date, crew_id: str) -> None:
        day_record = next(
            (cd for cd in plan.plan.days if cd.crew_id == crew_id and cd.day == day),
            None,
        )
        if not day_record or not day_record.stops:
            if day_record:
                day_record.total_drive_minutes = 0
                day_record.total_work_minutes = 0
                day_record.utilization = 0.0
                day_record.overbooked = False
            return
        crew = store.get_crew(crew_id)
        if not crew:
            return

        # Greedy nearest-neighbor from crew base
        remaining_jobs = [store.get_job(s.job_id) for s in day_record.stops]
        remaining_jobs = [j for j in remaining_jobs if j]

        ordered: list[Job] = []
        cur_lat, cur_lng = crew.base_lat, crew.base_lng
        while remaining_jobs:
            nxt = min(
                remaining_jobs,
                key=lambda j: haversine_km(cur_lat, cur_lng, j.lat, j.lng),
            )
            ordered.append(nxt)
            cur_lat, cur_lng = nxt.lat, nxt.lng
            remaining_jobs.remove(nxt)

        stops: list[ScheduledStop] = []
        cur_lat, cur_lng = crew.base_lat, crew.base_lng
        cursor = 0
        total_drive = 0
        total_work = 0
        for idx, j in enumerate(ordered):
            d_km = haversine_km(cur_lat, cur_lng, j.lat, j.lng)
            travel = drive_minutes(d_km)
            cursor += travel
            total_drive += travel
            stops.append(
                ScheduledStop(
                    job_id=j.id,
                    order=idx,
                    start_minute=cursor,
                    travel_minutes_before=travel,
                    duration_minutes=j.estimated_minutes,
                )
            )
            cursor += j.estimated_minutes
            total_work += j.estimated_minutes
            cur_lat, cur_lng = j.lat, j.lng

        return_drive = drive_minutes(haversine_km(cur_lat, cur_lng, crew.base_lat, crew.base_lng))
        total_drive += return_drive
        load = cursor + return_drive
        day_record.stops = stops
        day_record.total_drive_minutes = total_drive
        day_record.total_work_minutes = total_work
        day_record.utilization = round(min(1.0, load / max(1, crew.daily_minutes)), 2)
        day_record.overbooked = load > crew.daily_minutes

    async def _draft_message(self, job, new_day, crew_name, reason, client) -> str:
        date_str = new_day.strftime("%A, %b %d")
        template = (
            f"Hi {client.name if client else 'there'},\n\n"
            f"We need to reschedule your {job.service_type.value.replace('_', ' ')} originally planned for this week. "
            f"Reason: {reason}.\n\n"
            f"We've reassigned the job to {crew_name} on {date_str}. "
            "Please reply YES to confirm, or let us know a time that works better.\n\n"
            "Thanks for your flexibility,\nClearView"
        )
        if llm.enabled:
            system = (
                "Write a brief, apologetic but confident reschedule message. "
                "Acknowledge the inconvenience, state the reason in one short clause, "
                "propose the new date, and prompt for confirmation."
            )
            user = (
                f"Client: {client.name if client else 'unknown'}\n"
                f"Service: {job.service_type.value}\n"
                f"Reason: {reason}\n"
                f"New date: {date_str}\n"
                f"New crew: {crew_name}\n"
                f"Address: {job.address}\n"
                f"Draft a reschedule message."
            )
            text = await llm.chat(system, user, max_tokens=260, temperature=0.5)
            return text or template
        return template

    @staticmethod
    def _fallback_client_message(job, success: bool) -> str:
        client = store.get_client(job.client_id)
        if success:
            return f"Hi {client.name if client else 'there'}, we'll be in touch shortly to confirm a new time."
        return (
            f"Hi {client.name if client else 'there'}, "
            "we couldn't find a slot this week that works for the original constraints. "
            "Our operations team will reach out personally to find a date that works for you."
        )

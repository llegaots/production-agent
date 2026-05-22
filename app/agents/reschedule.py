"""ReschedulerAgent - handles disruption to an already-planned week.

Anthropic pattern: **Transparent decision-making**.

A reschedule run is triggered by:
  - weather day off
  - equipment failure
  - client cancellation / unavailability
  - crew callout

The agent enumerates *all* viable ``(day, crew)`` slots within the job's
allowed window, scores each one explicitly (day proximity, same-crew
continuity, headroom), emits the top candidates as events ("show the
agent's planning steps"), then picks #1, resequences the day route, and
drafts an explanatory message to the client.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from ..llm import llm
from ..models import (
    AgentEvent,
    CrewDay,
    Job,
    JobStatus,
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

        # 2) Enumerate ALL viable (day, crew) candidates with explicit
        #    trade-off scores. Anthropic principle: "show the agent's
        #    planning steps" - we emit the candidate set so the user can
        #    see the decision rationale, not just the final choice.
        crews_by_id = {c.id: c for c in store.list_crews()}
        candidate_days: list[date] = []
        start = original_day or job.earliest_date
        d = start
        while d <= job.latest_date:
            d = d + timedelta(days=1)
            if d.weekday() < 5:
                candidate_days.append(d)
        d = job.earliest_date
        while d < start:
            if d.weekday() < 5 and d not in candidate_days:
                candidate_days.append(d)
            d = d + timedelta(days=1)

        candidates: list[dict] = []
        for day in candidate_days:
            for crew in store.list_crews():
                if set(job.required_skills) - set(crew.skills):
                    continue
                crew_kinds = set()
                for eid in crew.equipment_ids:
                    e = store.get_equipment(eid)
                    if e:
                        crew_kinds.add(e.kind)
                if set(job.required_equipment) - crew_kinds:
                    continue

                day_record = next(
                    (cd for cd in plan.plan.days if cd.crew_id == crew.id and cd.day == day),
                    None,
                )
                used = (
                    day_record.total_work_minutes + day_record.total_drive_minutes
                    if day_record else 0
                )
                if used + job.estimated_minutes + 30 > crew.daily_minutes:
                    continue

                headroom = crew.daily_minutes - used - job.estimated_minutes - 30
                day_distance = abs((day - (original_day or day)).days)
                same_crew = 1 if crew.id == original_crew else 0
                # Score: prefer (1) sooner days, (2) same crew (continuity for
                # the client), (3) more headroom (less risk of overrun).
                score = (
                    100
                    - day_distance * 20
                    + same_crew * 8
                    + min(20, headroom // 30)
                )
                candidates.append(
                    {
                        "day": day,
                        "crew_id": crew.id,
                        "crew_name": crew.name,
                        "score": int(score),
                        "headroom_min": int(headroom),
                        "day_distance": int(day_distance),
                        "same_crew_as_before": bool(same_crew),
                    }
                )

        candidates.sort(key=lambda c: -c["score"])
        top = candidates[:5]
        if top:
            await emit(
                "evaluate",
                f"Evaluated {len(candidates)} viable slot(s); top {len(top)} shown.",
                detail={
                    "candidates": [
                        {**c, "day": c["day"].isoformat()} for c in top
                    ]
                },
            )
            for rank, c in enumerate(top, start=1):
                same = " (same crew)" if c["same_crew_as_before"] else ""
                await emit(
                    "candidate",
                    f"#{rank}: {c['crew_name']} on {c['day'].isoformat()}{same} "
                    f"— score {c['score']}, {c['headroom_min']}m headroom, "
                    f"{c['day_distance']}d from original.",
                )

        if not candidates:
            await emit("fail", f"No valid slot found for {job_id} within window.")
            client_msg = self._fallback_client_message(job, success=False)
            return RescheduleResult(
                job_id=job_id, succeeded=False, client_message=client_msg, events=events
            )

        chosen = candidates[0]
        new_day = chosen["day"]
        new_crew_id = chosen["crew_id"]
        day_record = next(
            (cd for cd in plan.plan.days if cd.crew_id == new_crew_id and cd.day == new_day),
            None,
        )
        crew = crews_by_id[new_crew_id]
        await emit(
            "decide",
            f"Selected #1: {crew.name} on {new_day.isoformat()} (score {chosen['score']}).",
            detail={"chosen": {**chosen, "day": chosen["day"].isoformat()}},
        )

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
            f"Placed {job_id} with {crew.name} on {new_day.isoformat()} (resequenced day route).",
            detail={"new_day": new_day.isoformat(), "new_crew_id": new_crew_id},
        )

        # 4) draft a client message
        client = store.get_client(job.client_id)
        msg = await self._draft_message(job, new_day, crew.name, reason, client)

        plan.client_messages[job.id] = msg
        plan.events.extend(events)
        store.set_job_status(job.id, JobStatus.RESCHEDULED)
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
        if not llm.enabled:
            return template

        system = (
            "You write brief reschedule messages for ClearView Exterior Services. "
            "Every message MUST: (1) apologize once - briefly, (2) state the reason in one "
            "short clause, (3) state the NEW date exactly as given, (4) state the new crew, "
            "(5) ask the client to confirm or to propose a different time. "
            "Do NOT promise refunds, discounts, or new pricing. Do NOT speculate about future weather. "
            "Two short paragraphs. Return the message only - no preamble."
        )
        few_shot = (
            "Example:\n"
            "Hi Maple Ridge HOA,\n\n"
            "Apologies for the change - our Tuesday slot is no longer viable due to a high "
            "wind advisory and we'd rather reschedule than work around safety constraints. "
            "We've moved your window cleaning to Thursday, May 21 with our Alpha crew.\n\n"
            "Please reply YES to confirm Thursday, or let us know a time later in the week "
            "that works better. Thanks for your flexibility, ClearView."
        )
        user = (
            few_shot
            + "\n\nNow draft a message with these facts:\n"
            + f"- Client: {client.name if client else 'unknown'}\n"
            + f"- Service: {job.service_type.value.replace('_', ' ')}\n"
            + f"- Reason: {reason}\n"
            + f"- New date: {date_str}\n"
            + f"- New crew: {crew_name}\n"
            + f"- Address: {job.address}\n"
            + "Return the message only."
        )
        text = await llm.chat(system, user, max_tokens=260, temperature=0.4)
        return text or template

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

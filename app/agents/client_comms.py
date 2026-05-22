"""ClientCommsAgent - drafts client-facing messages for scheduled jobs.

When an LLM is configured the agent uses it to write a warm,
professional note tailored to the client and job. Without an LLM, a
clean template is used so the system stays demoable.
"""
from __future__ import annotations

from datetime import date

from ..llm import llm
from ..storage import store
from .base import Agent, AgentContext


def _arrival_window(start_minute: int) -> str:
    base = 8 * 60  # shifts start at 8am
    start = base + start_minute
    end = start + 60
    return f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}"


class ClientCommsAgent(Agent):
    name = "ClientCommsAgent"

    async def run(self, ctx: AgentContext) -> None:
        crew_days = ctx.blackboard.get("crew_days", [])
        jobs_by_id = {j.id: j for j in ctx.jobs}
        crews_by_id = {c.id: c for c in ctx.crews}
        messages: dict[str, str] = {}

        await ctx.emit(self.name, "start", "Drafting client confirmation messages.")

        for cd in crew_days:
            crew = crews_by_id[cd.crew_id]
            for stop in cd.stops:
                job = jobs_by_id[stop.job_id]
                client = store.get_client(job.client_id)
                if not client:
                    continue
                arrival = _arrival_window(stop.start_minute)
                date_str = cd.day.strftime("%A, %b %d")

                template = (
                    f"Hi {client.name},\n\n"
                    f"This is ClearView Exterior Services confirming your {job.service_type.value.replace('_', ' ')} "
                    f"on {date_str}. Our {crew.name} crew is scheduled to arrive between {arrival} "
                    f"at {job.address}. We've allocated approximately {job.estimated_minutes} minutes for the work.\n\n"
                    "Please reply YES to confirm, or RESCHEDULE if this window no longer works. "
                    "If we don't hear back 24h before service we'll assume you're good to go.\n\n"
                    "Thanks,\nClearView"
                )

                if llm.enabled:
                    system = (
                        "You write short, warm, professional confirmation messages for a "
                        "window-cleaning and exterior services company. Always include the "
                        "service date, an arrival window, the address, and a clear confirm/"
                        "reschedule prompt. Two short paragraphs maximum."
                    )
                    user = (
                        f"Client: {client.name}\n"
                        f"Preferred contact: {client.preferred_contact}\n"
                        f"Service: {job.service_type.value}\n"
                        f"Date: {date_str}\n"
                        f"Arrival window: {arrival}\n"
                        f"Address: {job.address}\n"
                        f"Crew: {crew.name}\n"
                        f"Estimated duration: {job.estimated_minutes} minutes\n"
                        f"Job notes: {job.notes or 'none'}\n"
                        f"Draft a confirmation message."
                    )
                    text = await llm.chat(system, user, max_tokens=260, temperature=0.5)
                    messages[job.id] = text or template
                else:
                    messages[job.id] = template

        ctx.blackboard["client_messages"] = messages
        await ctx.emit(
            self.name,
            "done",
            f"Drafted {len(messages)} client message{'s' if len(messages) != 1 else ''}.",
        )

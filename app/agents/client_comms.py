"""ClientCommsAgent - routes, drafts, evaluates, and revises client messages.

This single agent orchestrates a small sub-pipeline that exercises three
Anthropic patterns at once:

  1. **Routing** — each job is classified into an *audience profile* (tone,
     channel, formality, max length) based on service type and the client's
     preferred contact channel. Different profiles use different prompts.
  2. **Parallelization (sectioning)** — for every drafted message, a
     :class:`MessageGuardrailAgent` (compliance/quality) and a
     :class:`MessageCriticAgent` (tone/clarity) run *concurrently*. Each
     focuses on its own aspect, which is more reliable than asking one
     prompt to do everything.
  3. **Evaluator-optimizer (the loop)** — when the critic's score is below
     a hard threshold the message is re-drafted *once*, feeding the
     critic's feedback back into the drafter. An explicit ``MAX_ITERATIONS``
     cap is the stopping condition.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ..llm import llm
from ..models import Job
from ..storage import store
from .base import Agent, AgentContext
from .message_critic import CritiqueResult, MessageCriticAgent
from .message_guardrail import GuardrailResult, MessageGuardrailAgent


MAX_ITERATIONS = 2  # stopping condition: drafter+critic loop runs at most twice


def _arrival_window(start_minute: int) -> str:
    base = 8 * 60
    start = base + start_minute
    end = start + 60
    return f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}"


def _audience_profile(job: Job) -> dict:
    """Routing decision: classify the audience.

    The profile is a small, explicit dict so downstream agents have a single,
    stable contract. It is intentionally not free-form text.
    """
    client = store.get_client(job.client_id)
    channel = (client.preferred_contact or "email").lower() if client else "email"

    is_commercial = job.service_type.value in ("high_rise",) or (
        client and any(
            w in client.name.lower() for w in ("llc", "tower", "plaza", "mgmt", "lofts", "hoa")
        )
    )
    if channel == "phone":
        tone = "warm-direct"
        max_words = 80
    elif is_commercial:
        tone = "formal"
        max_words = 140
    else:
        tone = "warm"
        max_words = 130

    return {
        "tone": tone,
        "channel": channel,
        "max_words": max_words,
        "is_commercial": bool(is_commercial),
        "service": job.service_type.value,
    }


class ClientCommsAgent(Agent):
    name = "ClientCommsAgent"

    def __init__(self) -> None:
        self.guardrail = MessageGuardrailAgent()
        self.critic = MessageCriticAgent()

    async def run(self, ctx: AgentContext) -> None:
        crew_days = ctx.blackboard.get("crew_days", [])
        jobs_by_id = {j.id: j for j in ctx.jobs}
        crews_by_id = {c.id: c for c in ctx.crews}

        messages: dict[str, str] = {}
        critic_scores: dict[str, int] = {}
        guardrail_flags_by_job: dict[str, list[str]] = {}

        await ctx.emit(self.name, "start", "Drafting client confirmation messages (routed, evaluated, guardrailed).")

        # Per-message sub-pipeline.
        for cd in crew_days:
            crew = crews_by_id[cd.crew_id]
            for stop in cd.stops:
                job = jobs_by_id[stop.job_id]
                client = store.get_client(job.client_id)
                if not client:
                    continue
                arrival = _arrival_window(stop.start_minute)
                date_str = cd.day.strftime("%A, %b %d")
                profile = _audience_profile(job)

                await ctx.emit(
                    self.name,
                    "route",
                    f"Job {job.id}: routed to '{profile['tone']}' / {profile['channel']} (max {profile['max_words']}w).",
                    detail={"job_id": job.id, "profile": profile},
                )

                # Iterative draft -> (critic || guardrail) -> maybe redraft.
                feedback: Optional[str] = None
                draft: str = ""
                critique: Optional[CritiqueResult] = None
                guardrail: Optional[GuardrailResult] = None

                for iteration in range(1, MAX_ITERATIONS + 1):
                    draft = await self._draft(
                        job, client, crew, date_str, arrival, profile, feedback
                    )

                    # Parallel sectioning: guardrail + critic run concurrently.
                    guardrail_task = asyncio.to_thread(
                        self.guardrail.check, draft, job, date_str, arrival
                    )
                    critic_task = self.critic.critique(
                        draft, job, profile, []  # filled in after guardrail result lands
                    )
                    guardrail, _critic_first = await asyncio.gather(guardrail_task, critic_task)
                    # Re-run critic with guardrail flags so it can fold them
                    # into the final score. This is cheap (no LLM call in the
                    # deterministic path) and gives the loop a single canonical
                    # score to branch on.
                    critique = await self.critic.critique(draft, job, profile, guardrail.flags)

                    await ctx.emit(
                        self.name,
                        f"iter_{iteration}",
                        f"Job {job.id} draft #{iteration}: score {critique.score}/100, "
                        f"guardrail {'pass' if guardrail.passed else 'FAIL'} ({len(guardrail.flags)} flag(s)).",
                        detail={
                            "job_id": job.id,
                            "iteration": iteration,
                            "score": critique.score,
                            "guardrail_passed": guardrail.passed,
                            "guardrail_flags": guardrail.flags,
                            "feedback": critique.feedback,
                        },
                    )

                    if not critique.revise:
                        break  # stop early when quality is good enough

                    feedback = critique.feedback
                    if iteration < MAX_ITERATIONS:
                        await ctx.emit(
                            self.name,
                            "revise",
                            f"Job {job.id}: redrafting (iteration {iteration + 1}) — {feedback[:80]}…",
                        )

                messages[job.id] = draft
                critic_scores[job.id] = critique.score if critique else 0
                if guardrail and not guardrail.passed:
                    guardrail_flags_by_job[job.id] = guardrail.flags

        ctx.blackboard["client_messages"] = messages
        ctx.blackboard["message_critic_scores"] = critic_scores
        ctx.blackboard["message_guardrail_flags"] = [
            {"job_id": jid, "flags": fl} for jid, fl in guardrail_flags_by_job.items()
        ]

        await ctx.emit(
            self.name,
            "done",
            f"Drafted {len(messages)} message(s); "
            f"{len(guardrail_flags_by_job)} flagged by guardrail; "
            f"avg quality {round(sum(critic_scores.values())/max(1,len(critic_scores)),1)}/100.",
        )

    # ---------- drafting ----------

    @staticmethod
    def _template(
        job: Job, client, crew, date_str: str, arrival: str, profile: dict
    ) -> str:
        service = job.service_type.value.replace("_", " ")
        if profile["channel"] == "phone":
            return (
                f"Hi {client.name.split(',')[0]}, this is ClearView. "
                f"Quick voicemail confirming your {service} on {date_str} — "
                f"our {crew.name} crew will be there between {arrival} at {job.address}. "
                f"Please give us a call back or text YES to confirm, or RESCHEDULE if "
                f"the time doesn't work. Thanks!"
            )
        if profile["is_commercial"] or profile["tone"] == "formal":
            return (
                f"Hello {client.name},\n\n"
                f"This message confirms ClearView Exterior Services is scheduled to perform "
                f"{service} at {job.address} on {date_str}. Crew {crew.name} will be on site "
                f"between {arrival}; estimated duration is {job.estimated_minutes} minutes.\n\n"
                f"Please reply to confirm, or contact us to reschedule. If we do not hear back "
                f"24 hours in advance we will proceed as scheduled.\n\n"
                f"Regards,\nClearView Exterior Services"
            )
        return (
            f"Hi {client.name},\n\n"
            f"This is ClearView Exterior Services confirming your {service} on {date_str}. "
            f"Our {crew.name} crew is scheduled to arrive between {arrival} at {job.address}. "
            f"We've allocated approximately {job.estimated_minutes} minutes for the work.\n\n"
            f"Please reply YES to confirm, or RESCHEDULE if this window no longer works. "
            f"If we don't hear back 24h before service we'll assume you're good to go.\n\n"
            f"Thanks,\nClearView"
        )

    async def _draft(
        self,
        job: Job,
        client,
        crew,
        date_str: str,
        arrival: str,
        profile: dict,
        feedback: Optional[str],
    ) -> str:
        baseline = self._template(job, client, crew, date_str, arrival, profile)
        if not llm.enabled:
            return baseline

        sys = self._system_prompt_for(profile)
        few_shot = self._few_shot_for(profile)
        user = (
            (few_shot + "\n\n" if few_shot else "")
            + "Now draft a message with these facts:\n"
            + f"- Client: {client.name}\n"
            + f"- Service: {job.service_type.value.replace('_', ' ')}\n"
            + f"- Date: {date_str}\n"
            + f"- Arrival window: {arrival}\n"
            + f"- Address: {job.address}\n"
            + f"- Crew: {crew.name}\n"
            + f"- Estimated duration: {job.estimated_minutes} minutes\n"
            + f"- Job notes: {job.notes or 'none'}\n"
            + f"- Tone: {profile['tone']}; channel: {profile['channel']}; "
            + f"max words: {profile['max_words']}.\n"
            + (
                "\nThe previous draft was rejected. Reviewer feedback to address:\n"
                + feedback
                + "\nRewrite the message to fix these issues. Keep the date, time window, "
                + "address, and call-to-action.\n"
                if feedback
                else ""
            )
            + "\nReturn the message only — no preamble, no markdown fences."
        )
        out = await llm.chat(sys, user, max_tokens=300, temperature=0.4)
        return out or baseline

    @staticmethod
    def _system_prompt_for(profile: dict) -> str:
        common = (
            "You write short client confirmation messages for ClearView Exterior Services, "
            "a window-cleaning and exterior services company. Every message MUST include: "
            "(1) the scheduled date exactly as given, (2) the arrival window exactly as given, "
            "(3) the address, and (4) a call-to-action asking the client to reply to confirm "
            "or to reschedule. Do not invent prices, names, or services not in the facts. "
            "Do not reference other clients."
        )
        if profile["channel"] == "phone":
            return (
                common
                + " The channel is a voicemail script. Plain text only — no markdown, no headings, "
                + "no bulleted lists. Under 80 words. Use a single short paragraph."
            )
        if profile["tone"] == "formal":
            return (
                common
                + " The audience is a commercial / HOA client. Use a formal register, no slang. "
                + "Two short paragraphs maximum."
            )
        return (
            common
            + " The audience is a residential client. Use a warm but professional tone. Two short paragraphs."
        )

    @staticmethod
    def _few_shot_for(profile: dict) -> str:
        if profile["channel"] == "phone":
            return (
                "Example (phone voicemail):\n"
                "Hi Sam, this is ClearView. Quick voicemail confirming your window cleaning on "
                "Tuesday, May 19 — our Alpha crew will be at 22 Vista Trail between 09:00-10:00. "
                "Please give us a call back or text YES to confirm, or RESCHEDULE if the time "
                "doesn't work. Thanks!"
            )
        if profile["tone"] == "formal":
            return (
                "Example (commercial):\n"
                "Hello Congress Tower LLC,\n\n"
                "This message confirms ClearView Exterior Services is scheduled to perform "
                "high-rise window cleaning at 100 Congress Ave on Monday, May 18. Crew Charlie "
                "will be on site between 08:00-09:00; estimated duration is 420 minutes.\n\n"
                "Please reply to confirm, or contact us to reschedule. Regards, ClearView."
            )
        return (
            "Example (residential):\n"
            "Hi Maple Ridge HOA,\n\n"
            "This is ClearView Exterior Services confirming your window cleaning on Monday, "
            "May 18. Our Alpha crew will arrive between 08:30-09:30 at 4501 Maple Ridge Dr. "
            "We've allocated about 180 minutes.\n\n"
            "Please reply YES to confirm, or RESCHEDULE if this window doesn't work. Thanks, ClearView."
        )

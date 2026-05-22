"""PlanReviewerAgent - evaluator over the assembled weekly plan.

Anthropic pattern: **Evaluator-optimizer (evaluator side).**

This agent scores the plan along measurable dimensions (revenue,
drive efficiency, schedule risk, customer-promise risk) and produces
structured findings. If an LLM is configured, it also writes a short
narrative review. The structured score is what downstream consumers
(future evaluator-optimizer loops, dashboards) can branch on; the
narrative is for humans.

Outputs to the blackboard under ``plan_review``:
    {
      "kpis": {revenue, total_minutes, drive_ratio, scheduled, deferred},
      "risk_score": 0..100,
      "top_concern": str | None,
      "recommendation": str | None,
      "narrative": str,
    }
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from ..llm import llm, safe_json
from ..models import CrewDay, Job
from ..storage import store
from .base import Agent, AgentContext, llm_trace_callback


class PlanReviewerAgent(Agent):
    name = "PlanReviewerAgent"

    async def run(self, ctx: AgentContext) -> None:
        crew_days: list[CrewDay] = ctx.blackboard.get("crew_days", [])
        unscheduled: list[str] = ctx.blackboard.get("unscheduled", [])
        equipment_conflicts = ctx.blackboard.get("equipment_conflicts", [])
        equipment_gaps = ctx.blackboard.get("equipment_gaps", [])
        message_guardrail_flags = ctx.blackboard.get("message_guardrail_flags", [])
        message_critic_scores = ctx.blackboard.get("message_critic_scores", {})

        await ctx.emit_tool(
            "plan_review",
            "invoke",
            "Computing KPIs, risk score, and optional LLM narrative.",
            {"crew_days": len(crew_days)},
        )
        await ctx.emit(self.name, "start", "Scoring the assembled plan.")

        jobs_by_id = {j.id: j for j in ctx.jobs}

        # ---- KPIs (deterministic) ----
        scheduled_ids: set[str] = set()
        total_work = 0
        total_drive = 0
        overbooked_days = 0
        for cd in crew_days:
            total_work += cd.total_work_minutes
            total_drive += cd.total_drive_minutes
            if cd.overbooked:
                overbooked_days += 1
            for s in cd.stops:
                scheduled_ids.add(s.job_id)

        revenue = sum(jobs_by_id[jid].price for jid in scheduled_ids if jid in jobs_by_id)
        deferred_revenue = sum(jobs_by_id[jid].price for jid in unscheduled if jid in jobs_by_id)
        total = total_work + total_drive
        drive_ratio = round(total_drive / total, 3) if total > 0 else 0.0

        # ---- Risk score (deterministic, 0-100) ----
        risk = 0.0
        # 1 - each overbooked crew-day is +12
        risk += overbooked_days * 12
        # 2 - each unscheduled job is +8
        risk += len(unscheduled) * 8
        # 3 - each unresolved equipment conflict/gap is +6
        risk += (len(equipment_conflicts) + len(equipment_gaps)) * 6
        # 4 - drive ratio above 0.25 starts costing points (1.5 / pct)
        if drive_ratio > 0.25:
            risk += (drive_ratio - 0.25) * 100 * 1.5
        # 5 - guardrail failures are serious (+10 each)
        risk += len(message_guardrail_flags) * 10
        # 6 - jobs scheduled at the latest allowed date (no slack) +3 each
        zero_slack = 0
        for cd in crew_days:
            for s in cd.stops:
                job = jobs_by_id.get(s.job_id)
                if job and cd.day == job.latest_date:
                    zero_slack += 1
        risk += zero_slack * 3

        risk_score = max(0, min(100, int(round(risk))))

        # ---- Identify top concern ----
        top_concern: Optional[str] = None
        recommendation: Optional[str] = None
        if message_guardrail_flags:
            top_concern = (
                f"{len(message_guardrail_flags)} client message(s) failed compliance/quality checks."
            )
            recommendation = "Review flagged messages in the Client Messages drawer before sending."
        elif equipment_gaps:
            top_concern = (
                f"{len(equipment_gaps)} job(s) are scheduled on a crew that lacks the required equipment."
            )
            recommendation = "Reassign to a capable crew, rent the gear, or defer."
        elif overbooked_days:
            top_concern = f"{overbooked_days} crew-day(s) are over capacity once drive time is included."
            recommendation = "Trim the smallest job from the overbooked day or move it to a lighter day."
        elif unscheduled:
            top_concern = f"{len(unscheduled)} job(s) could not be placed this week."
            recommendation = "Extend the planning window or add overtime capacity to the most-capable crew."
        elif drive_ratio > 0.3:
            top_concern = f"Drive time is {int(drive_ratio*100)}% of the week."
            recommendation = "Tighten geographic clustering or run another route-optimization pass."
        elif zero_slack:
            top_concern = f"{zero_slack} job(s) are scheduled on their latest-allowed date (no slack)."
            recommendation = "Watch the weather forecast for these days; have a backup slot ready."

        kpis = {
            "scheduled_jobs": len(scheduled_ids),
            "deferred_jobs": len(unscheduled),
            "revenue_scheduled": round(revenue, 2),
            "revenue_deferred": round(deferred_revenue, 2),
            "total_work_minutes": total_work,
            "total_drive_minutes": total_drive,
            "drive_ratio": drive_ratio,
            "overbooked_crew_days": overbooked_days,
            "equipment_conflicts": len(equipment_conflicts),
            "equipment_gaps": len(equipment_gaps),
            "guardrail_flags": len(message_guardrail_flags),
            "avg_message_quality": (
                round(sum(message_critic_scores.values()) / len(message_critic_scores), 2)
                if message_critic_scores else None
            ),
        }

        narrative = await self._narrate(kpis, risk_score, top_concern, recommendation)

        review = {
            "kpis": kpis,
            "risk_score": risk_score,
            "top_concern": top_concern,
            "recommendation": recommendation,
            "narrative": narrative,
        }
        ctx.blackboard["plan_review"] = review

        await ctx.emit(
            self.name,
            "done",
            f"Plan reviewed. Risk score {risk_score}/100. {top_concern or 'No critical concerns.'}",
            detail=review,
        )

    @staticmethod
    async def _narrate(
        kpis: dict, risk_score: int, top_concern: Optional[str], recommendation: Optional[str]
    ) -> str:
        # Deterministic narrative fallback - always produced so the system works
        # without an LLM.
        rev = kpis["revenue_scheduled"]
        deferred = kpis["revenue_deferred"]
        drive_pct = int(kpis["drive_ratio"] * 100)
        deterministic = (
            f"Risk {risk_score}/100. Scheduled {kpis['scheduled_jobs']} jobs (${rev:,.0f} of revenue), "
            f"deferred {kpis['deferred_jobs']} (${deferred:,.0f}). Drive is {drive_pct}% of the week. "
            + (f"Top concern: {top_concern} " if top_concern else "No critical concerns. ")
            + (f"Suggestion: {recommendation}" if recommendation else "")
        ).strip()

        if not llm.enabled:
            return deterministic

        sys = (
            "You are an experienced operations supervisor at a service-based business. "
            "Given KPIs and a risk score, write a 2-3 sentence executive review of the week. "
            "Be concrete and specific. Reference KPIs by their actual numbers. End with one "
            "action the supervisor should take today. Do NOT invent facts that aren't in the input."
        )
        user = (
            "KPIs (JSON):\n"
            + json.dumps(kpis, indent=2)
            + f"\n\nRisk score: {risk_score}/100"
            + (f"\nTop concern: {top_concern}" if top_concern else "")
            + (f"\nRecommendation: {recommendation}" if recommendation else "")
            + "\n\nWrite the review."
        )
        out = await llm.chat(
            sys,
            user,
            max_tokens=220,
            temperature=0.3,
            trace=llm_trace_callback(ctx),
            trace_label="plan_reviewer.narrative",
        )
        return out or deterministic

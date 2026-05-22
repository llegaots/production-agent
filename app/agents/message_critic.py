"""MessageCriticAgent - evaluator for client message quality.

Anthropic pattern: **Evaluator-optimizer (evaluator side).**

The critic scores a drafted message on five dimensions and emits a
single feedback string the drafter can use to revise. A re-draft is
triggered only when the score is below threshold *and* we are still
within the iteration cap, matching Anthropic's recommendation that
agentic loops include explicit stopping conditions.

Without an LLM the critic uses deterministic checks. With an LLM the
critic asks for structured JSON output (score + feedback), again
following the principle that LLM responses should be structured when
the agent needs to branch on them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..llm import TraceFn, llm, safe_json
from ..models import Job
from ..storage import store


@dataclass
class CritiqueResult:
    job_id: str
    score: int  # 0-100
    feedback: str
    revise: bool


class MessageCriticAgent:
    name = "MessageCriticAgent"

    PASS_THRESHOLD = 75

    @classmethod
    async def critique(
        cls,
        message: str,
        job: Job,
        audience_profile: dict,
        guardrail_flags: list[str],
        trace: TraceFn | None = None,
    ) -> CritiqueResult:
        score, feedback = cls._deterministic_score(message, job, audience_profile, guardrail_flags)

        if llm.enabled:
            llm_score, llm_feedback = await cls._llm_score(
                message, job, audience_profile, trace=trace
            )
            if llm_score is not None:
                # Combine: the LLM is asked to judge tone/clarity; the
                # deterministic pass already checked structural facts.
                score = int(round((score + llm_score) / 2))
                if llm_feedback:
                    feedback = f"{feedback} | LLM critic: {llm_feedback}".strip(" |")

        revise = score < cls.PASS_THRESHOLD
        return CritiqueResult(job_id=job.id, score=score, feedback=feedback, revise=revise)

    # ---------- deterministic pass ----------
    @staticmethod
    def _deterministic_score(
        message: str, job: Job, audience_profile: dict, guardrail_flags: list[str]
    ) -> tuple[int, str]:
        m = message or ""
        ml = m.lower()
        feedback_bits: list[str] = []
        score = 100

        # Guardrail violations dominate the score.
        score -= 25 * len(guardrail_flags)
        if guardrail_flags:
            feedback_bits.append("Guardrail issues: " + "; ".join(guardrail_flags))

        # Channel-appropriateness.
        channel = audience_profile.get("channel", "email")
        if channel == "phone":
            # Phone-call scripts should be short and not contain markdown/headings.
            if len(m) > 480:
                score -= 15
                feedback_bits.append("Phone-channel message should be under ~80 words.")
            if any(ch in m for ch in ("**", "##", "- ")):
                score -= 10
                feedback_bits.append("Phone-channel message must not contain markdown formatting.")
        elif channel == "email":
            if len(m) < 80:
                score -= 10
                feedback_bits.append("Email feels too terse; add a brief next-step sentence.")

        # Greeting present.
        client = store.get_client(job.client_id)
        if client and client.name.split()[0].lower() not in ml:
            score -= 5
            feedback_bits.append("Greeting could address the client by name.")

        # Service mentioned.
        service_pretty = job.service_type.value.replace("_", " ")
        if service_pretty not in ml:
            score -= 5
            feedback_bits.append(f"Could explicitly reference the service ({service_pretty}).")

        # Polite sign-off / company name.
        if "clearview" not in ml:
            score -= 5
            feedback_bits.append("Sign-off doesn't include the company name (ClearView).")

        # Specialty tone notes from audience profile.
        tone_required = audience_profile.get("tone")
        if tone_required == "formal" and any(w in ml for w in (" hey ", "y'all", "no worries")):
            score -= 8
            feedback_bits.append("Tone should be formal for this account.")

        score = max(0, min(100, score))
        return score, " | ".join(feedback_bits) or "No deterministic issues."

    # ---------- LLM pass ----------
    @staticmethod
    async def _llm_score(
        message: str,
        job: Job,
        audience_profile: dict,
        trace: TraceFn | None = None,
    ) -> tuple[Optional[int], Optional[str]]:
        sys = (
            "You are a strict reviewer of client communications for a service business. "
            "Score the draft on a 0-100 scale considering clarity, tone fit, completeness "
            "(date, time window, address, call-to-action), and brevity. "
            "Return STRICT JSON only, no prose, no markdown fences. "
            "Shape: {\"score\": <int 0-100>, \"feedback\": \"<one short sentence>\"}"
        )
        user = (
            f"Audience profile: {json.dumps(audience_profile)}\n"
            f"Service: {job.service_type.value}\n\n"
            f"Draft message:\n---\n{message}\n---\n\n"
            "Return JSON only."
        )
        raw = await llm.chat(
            sys,
            user,
            max_tokens=120,
            temperature=0.0,
            trace=trace,
            trace_label="message_critic.score",
        )
        data = safe_json(raw or "")
        if not data:
            return None, None
        try:
            score = int(data.get("score"))
            feedback = str(data.get("feedback", "")).strip()
            return max(0, min(100, score)), feedback
        except (TypeError, ValueError):
            return None, None

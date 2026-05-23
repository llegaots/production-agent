"""LLM schedule critic (Anthropic) with deterministic rule fallback."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings
from app.critic.schemas import CriticVerdict, DeterministicMetrics, ReviewScheduleInput


def _rule_based_verdict(
    metrics: DeterministicMetrics,
    inp: ReviewScheduleInput,
) -> CriticVerdict:
    """Deterministic fallback when no API key or LLM parse fails."""
    issues = list(metrics.deterministic_issues)
    approved = len(issues) == 0 and inp.optimizer_result.is_success

    if approved:
        feedback = (
            "Schedule passes deterministic checks. Proceed to client messaging "
            "after dispatcher confirmation."
        )
    else:
        actions = []
        if metrics.preference_violation_count > 0:
            actions.append(
                "Reassign jobs to preferred crews or update preferences in the job records."
            )
        if metrics.week_fill_score < 0.85:
            actions.append(
                "Add crews, extend shifts, or relax time windows to schedule remaining jobs."
            )
        if metrics.equipment_fit_score < 0.95:
            actions.append(
                "Move jobs to crews with required equipment or adjust crew_equipment assignments."
            )
        for msg in metrics.deterministic_issues:
            if "geographic spread" in msg:
                actions.append(
                    "Reorder routes to cluster nearby stops; avoid cross-region zig-zags."
                )
            if "drive time" in msg:
                actions.append("Reduce travel by swapping jobs between crews or adding a nearer crew.")
        feedback = "Revise the plan: " + " ".join(actions) if actions else "Fix flagged metrics and re-run the optimizer."

    return CriticVerdict(approved=approved, issues=issues, feedback_prompt=feedback)


def _build_user_payload(
    metrics: DeterministicMetrics,
    inp: ReviewScheduleInput,
    run_history: list[dict[str, Any]],
) -> str:
    payload = {
        "target_date": inp.target_date.isoformat(),
        "optimizer_status": inp.optimizer_result.status,
        "assigned_jobs": inp.optimizer_result.assigned_job_ids,
        "unassigned_jobs": inp.optimizer_result.unassigned_job_ids,
        "routes": [r.model_dump() for r in inp.optimizer_result.routes],
        "deterministic_metrics": metrics.model_dump(mode="json"),
        "prior_reviews": run_history,
    }
    return json.dumps(payload, indent=2)


SYSTEM_PROMPT = """You are the Plan Reviewer for a window-cleaning operations scheduler.

You receive:
1) Deterministic metrics (drive minutes, geographic spread, preference violations, week-fill, equipment-fit)
2) The proposed crew routes and job assignments
3) Prior critic feedback from earlier attempts (if any)

Respond with ONLY valid JSON (no markdown fences):
{
  "approved": boolean,
  "issues": ["specific, actionable issue", ...],
  "feedback_prompt": "Instructions for the orchestrator to fix the plan in one paragraph"
}

Reject (approved=false) when:
- Jobs are geographically scattered for a crew-day
- Preferred crews are ignored without justification
- Equipment or skills cannot service assigned jobs
- Too many jobs remain unassigned
- Drive time is excessive relative to shift length

Approve only when the plan is operationally sound for field execution. Be specific in issues."""


def _parse_llm_json(text: str) -> CriticVerdict:
    text = text.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("No JSON object in LLM response")
    data = json.loads(match.group())
    return CriticVerdict.model_validate(data)


def _call_anthropic(
    metrics: DeterministicMetrics,
    inp: ReviewScheduleInput,
    run_history: list[dict[str, Any]],
) -> CriticVerdict:
    settings = get_settings()
    api_key = getattr(settings, "anthropic_api_key", None)
    if not api_key:
        import os

        api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _rule_based_verdict(metrics, inp)

    model = getattr(settings, "anthropic_model", None) or "claude-sonnet-4-20250514"

    body = {
        "model": model,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": _build_user_payload(metrics, inp, run_history),
            }
        ],
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    try:
        verdict = _parse_llm_json(text)
    except Exception:
        verdict = _rule_based_verdict(metrics, inp)
        if not verdict.approved:
            verdict.issues.append("LLM response could not be parsed; used rule-based review.")
        return verdict

    # Merge deterministic issues the LLM may have missed
    merged_issues = list(dict.fromkeys(metrics.deterministic_issues + verdict.issues))
    approved = verdict.approved and not metrics.deterministic_issues
    return CriticVerdict(
        approved=approved,
        issues=merged_issues,
        feedback_prompt=verdict.feedback_prompt,
    )


def run_llm_critic(
    metrics: DeterministicMetrics,
    inp: ReviewScheduleInput,
    run_history: list[dict[str, Any]],
    *,
    use_llm: bool = True,
) -> CriticVerdict:
    if not use_llm:
        return _rule_based_verdict(metrics, inp)
    return _call_anthropic(metrics, inp, run_history)

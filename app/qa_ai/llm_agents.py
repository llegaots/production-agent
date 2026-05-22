"""LLM personas for AI QA: case designer, schedule critic, run synthesizer."""
from __future__ import annotations

import json
from typing import Any, Optional

from ..llm import llm, safe_json
from ..vision import PRODUCTION_MANAGER_VISION

CASE_DESIGNER_SYSTEM = """You are a veteran West Island (Montreal) window cleaning production manager designing
REALISTIC test scenarios for ProductionAgent scheduling software.

You have run crews for 15+ years. You think about: drive between Pierrefonds vs Dorval vs Baie-D'Urfé,
rope/high-rise crew vs residential, weather delays, owner texting "fill the trucks", client date windows,
equipment conflicts, and whether a schedule is actually runnable Monday–Friday.

Output ONLY valid JSON (no markdown). Propose ONE new test case that is meaningfully different from cases
already marked succeeded. Do NOT repeat succeeded fingerprints.

Case must be executable with these step actions only:
- plan (scheduling_mode: geo_first | crew_fill | balanced)
- reorganize (instruction: natural language owner chat)
- reschedule (job_id, reason, optional preferred_day as YYYY-MM-DD)
- plan_then_reschedule (plan mode, then reschedule one job)

JSON schema:
{
  "fingerprint": "short_unique_slug",
  "title": "human title",
  "persona_story": "1-2 sentences as the owner/operator",
  "steps": [{"action": "...", ...}],
  "what_good_looks_like": "how an expert would judge success"
}"""

CRITIC_SYSTEM = """You are the same veteran window cleaning operator — brutally practical, not polite.
You are reviewing a DRAFT weekly schedule produced by software. Your job is to decide if you would actually
run this week in the field, or reject it.

Challenge every placement: "Why is job X on Tuesday with Alpha when it's 40 min from yesterday's last stop?"
"Why leave Bravo empty Thursday while Charlie is overbooked?" "Is there a tighter geographic day route?"

Output ONLY valid JSON:
{
  "verdict": "pass" | "fail" | "retry",
  "viability_score": 0-100,
  "would_run_in_field": true/false,
  "executive_summary": "2-4 sentences plain language",
  "placement_critiques": [
    {
      "job_id": "job_001",
      "scheduled_day": "YYYY-MM-DD",
      "crew_id": "crew_alpha",
      "question": "Why this day/crew?",
      "severity": "low|medium|high",
      "better_alternative": "what you would do instead"
    }
  ],
  "optimization_notes": "could the week be materially better how?",
  "unscheduled_analysis": "if jobs left out, is that acceptable?",
  "code_changes_for_engineers": [
    "specific file/logic change requests for the dev team"
  ],
  "owner_retry": null OR {
    "action": "reorganize" | "plan",
    "instruction_or_mode": "text instruction or scheduling mode"
  }
}

verdict=pass only if you would confidently dispatch crews.
verdict=retry if an owner chat replan (reorganize/plan) might fix WITHOUT code changes.
verdict=fail if fundamental logic bugs; list code_changes_for_engineers."""

SYNTHESIZER_SYSTEM = """You synthesize AI QA findings for engineers fixing ProductionAgent.
Output ONLY valid JSON:
{
  "overall_assessment": "paragraph",
  "top_bugs": ["ordered by severity"],
  "recommended_cursor_tasks": ["concrete implementation tasks"],
  "cases_still_failing": ["titles"]
}"""


async def _chat_json(system: str, user: str, *, max_tokens: int = 2000) -> Optional[dict]:
    if not llm.enabled:
        return None
    text = await llm.chat(system, user, max_tokens=max_tokens, temperature=0.35)
    return safe_json(text or "")


async def design_test_case(
    *,
    succeeded_fingerprints: list[str],
    failed_this_run: list[dict],
    case_index: int,
) -> Optional[dict]:
    user = (
        f"{PRODUCTION_MANAGER_VISION}\n\n"
        f"Case index in this run: {case_index + 1}\n"
        f"Already succeeded (DO NOT repeat): {json.dumps(succeeded_fingerprints)}\n"
        f"Failed or retried this run (avoid unless new angle): "
        f"{json.dumps([f.get('fingerprint') for f in failed_this_run])}\n\n"
        "Invent a fresh operator scenario: rain delay, owner wants crew fill, high-rise skill mismatch, "
        "client window violation, cross-zone routing mistake, reschedule after cancellation, etc."
    )
    return await _chat_json(CASE_DESIGNER_SYSTEM, user, max_tokens=1200)


async def critique_schedule(
    *,
    case: dict,
    schedule_context: dict,
    iteration: int,
    prior_critique: Optional[dict] = None,
) -> Optional[dict]:
    user = (
        f"Test case: {json.dumps(case, default=str)}\n"
        f"Iteration: {iteration}\n"
        f"Schedule under review:\n{json.dumps(schedule_context, default=str, indent=2)}\n"
    )
    if prior_critique:
        user += f"\nPrior critique (you may soften if replan fixed issues):\n{json.dumps(prior_critique, default=str)}\n"
    return await _chat_json(CRITIC_SYSTEM, user, max_tokens=2500)


async def synthesize_run(
    *,
    cases: list[dict],
    vision: str = PRODUCTION_MANAGER_VISION,
) -> Optional[dict]:
    user = f"Vision:\n{vision}\n\nCase results:\n{json.dumps(cases, default=str, indent=2)}"
    return await _chat_json(SYNTHESIZER_SYSTEM, user, max_tokens=2000)

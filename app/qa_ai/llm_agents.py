"""LLM personas for AI QA: case designer, schedule critic, run synthesizer."""
from __future__ import annotations

import json
from typing import Any, Optional

from ..llm import llm, safe_json
from ..vision import PRODUCTION_MANAGER_VISION

CASE_DESIGNER_SYSTEM = """You are a veteran West Island (Montreal) window cleaning production manager designing
REALISTIC test scenarios for ProductionAgent scheduling software.

You have run crews for 15+ years. You understand: drive between Pierrefonds vs Dorval vs Baie-D'Urfé,
rope/high-rise crew vs residential, weather delays, owner texting "fill the trucks", equipment conflicts.

Output ONLY raw JSON. NEVER wrap the JSON in markdown code fences.
Start your response with `{` and end with `}`. Keep narrative fields under 200 characters.

═══ CRITICAL: TEST JOBS ═══════════════════════════════════════════════════════
You MUST include a "test_jobs" array. These are REAL jobs the system will insert into the
database before running the scenario. The scheduler will plan against ONLY these jobs.

Each test_job must have:
  "id"                  — unique slug (no spaces), will be prefixed qa_ automatically
  "service_type"        — window_cleaning | gutter_cleaning | pressure_washing | high_rise | solar_panel_cleaning
  "address"             — real West Island address
  "lat", "lng"          — real coordinates (West Island: lat 45.35–45.52, lng -74.05 to -73.65)
  "estimated_minutes"   — realistic (window residential 60–180, gutter 90–240, high_rise 180–480)
  "difficulty"          — 1–5
  "required_skills"     — array from: rope_access, lift_operator, pressure_wash, ladder_cert, glass_restoration
  "required_equipment"  — array from: rope_kit, ladder_28, ladder_32, pressure_washer, water_fed_pole, scissor_lift, van
  "earliest_date"       — MUST be 2026-07-06 to 2026-07-10 (the planning week)
  "latest_date"         — MUST be 2026-07-06 to 2026-07-10 (same week)
  "price"               — realistic ($150–$2800)

CREW CAPABILITIES (do not assign jobs that no crew can handle):
  crew_alpha  — skills: ladder_cert, pressure_wash  — equipment: pressure_washer, water_fed_pole, ladder_28, van
  crew_bravo  — skills: ladder_cert, lift_operator, pressure_wash, glass_restoration  — equipment: pressure_washer, water_fed_pole, scissor_lift, ladder_28, ladder_32, van
  crew_charlie — skills: rope_access, lift_operator, glass_restoration  — equipment: rope_kit, van
  crew_delta  — skills: ladder_cert, pressure_wash  — equipment: pressure_washer, water_fed_pole, ladder_28, van

The reschedule step "job_id" MUST match one of the "id" values you define in test_jobs
(the system prefixes qa_ so use the plain id). Use preferred_day as YYYY-MM-DD within 2026-07-06..2026-07-10.

═══ VARIETY ═══════════════════════════════════════════════════════════════════
Pick a category that is LEAST tested (you will be told coverage).
Fingerprint MUST start with category letter: "C_rope_conflict" or "F_rain_monday".
Categories:
  A) geo_routing  B) crew_fill  C) equipment_conflict  D) skill_gap
  E) date_window  F) rain_reschedule  G) multi_crew_balance  H) revenue_priority

═══ JSON SCHEMA ════════════════════════════════════════════════════════════════
{
  "fingerprint": "LETTER_slug",
  "category": "A|B|C|D|E|F|G|H",
  "title": "...",
  "persona_story": "...",
  "test_jobs": [ { ...job fields... }, ... ],
  "steps": [
    {"action": "plan", "scheduling_mode": "geo_first|crew_fill|balanced|revenue_priority"},
    {"action": "reorganize", "instruction": "owner chat text"},
    {"action": "reschedule", "job_id": "EXACT_ID_FROM_TEST_JOBS", "reason": "...", "preferred_day": "2026-07-08"},
    {"action": "plan_then_reschedule", "scheduling_mode": "...", "job_id": "EXACT_ID", "reason": "..."}
  ],
  "what_good_looks_like": "observable scheduling outcome"
}"""

CRITIC_SYSTEM = """You are the same veteran window cleaning operator — brutally practical, not polite.
You are reviewing a DRAFT weekly schedule produced by software. Your job is to decide if you would actually
run this week in the field, or reject it.

IMPORTANT: The schedule context shows REAL job IDs (prefixed qa_) from the test scenario.
Evaluate using ONLY the job IDs shown in the schedule. Do NOT reference fictional names like Job#401.
If the schedule is empty (no crew_days, no stops) — that is a critical failure: say so plainly.

Challenge every placement using real IDs: "Why is qa_rope_job_a on Tuesday with crew_bravo when it needs
rope_access and crew_bravo doesn't have it?" "Why are qa_job_1 and qa_job_2 both on Wednesday when they
are 25 km apart?" "The schedule has 0 stops — the planner produced nothing."

Output ONLY raw JSON. NEVER wrap the JSON in markdown code fences (no ```json, no ```).
Start your response with `{` and end with `}`. Keep prose fields under 280 characters each.
Schema:
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
Output ONLY raw JSON. NEVER wrap the JSON in markdown code fences. Start with `{`, end with `}`.
Schema:
{
  "overall_assessment": "paragraph",
  "top_bugs": ["ordered by severity"],
  "recommended_cursor_tasks": ["concrete implementation tasks"],
  "cases_still_failing": ["titles"]
}"""


def _llm_failure_message(text: Optional[str]) -> Optional[str]:
    if not text:
        return "LLM returned empty response."
    if text.startswith("[LLM fallback after error:"):
        return text.removeprefix("[LLM fallback after error:").rstrip("]").strip()
    return None


async def _chat_json(
    system: str, user: str, *, max_tokens: int = 2000
) -> tuple[Optional[dict], Optional[str]]:
    """Returns (parsed_json, error_message). Uses the cheaper QA model when set."""
    if not llm.enabled:
        return None, "LLM not configured (add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env)."
    text = await llm.chat(
        system,
        user,
        max_tokens=max_tokens,
        temperature=0.35,
        trace_label="qa.llm",
        model_override=llm.qa_model,
    )
    err = _llm_failure_message(text)
    if err:
        return None, err
    data = safe_json(text or "")
    if not data:
        preview = (text or "")[:240]
        return None, f"LLM response was not valid JSON. Preview: {preview}"
    return data, None


def _category_coverage(succeeded_fingerprints: list[str], failed_this_run: list[dict]) -> dict[str, int]:
    """Count how many times each A-H category has appeared in succeeded + failed cases."""
    counts: dict[str, int] = {c: 0 for c in "ABCDEFGH"}
    for fp in succeeded_fingerprints:
        letter = fp[0].upper() if fp and fp[0].upper() in counts else None
        if letter:
            counts[letter] += 1
    for rec in failed_this_run:
        fp = rec.get("fingerprint", "")
        letter = fp[0].upper() if fp and fp[0].upper() in counts else None
        if letter:
            counts[letter] += 1
    return counts


async def design_test_case(
    *,
    succeeded_fingerprints: list[str],
    failed_this_run: list[dict],
    case_index: int,
) -> Optional[dict]:
    coverage = _category_coverage(succeeded_fingerprints, failed_this_run)
    # Least-covered categories first (alphabetical tiebreak).
    by_coverage = sorted(coverage.items(), key=lambda kv: (kv[1], kv[0]))
    least_covered = [k for k, v in by_coverage[:3]]
    saturated    = [k for k, v in coverage.items() if v >= 2]

    user = (
        f"{PRODUCTION_MANAGER_VISION}\n\n"
        f"Case index in this run: {case_index + 1}\n"
        f"Already succeeded (DO NOT repeat these fingerprints): {json.dumps(succeeded_fingerprints)}\n"
        f"Failed or retried this run: "
        f"{json.dumps([f.get('fingerprint') for f in failed_this_run])}\n\n"
        f"Category coverage so far: {json.dumps(coverage)}\n"
        f"Saturated categories (2+ cases already — AVOID these): {saturated}\n"
        f"Least-tested categories — PICK ONE OF THESE: {least_covered}\n\n"
        "Design a scenario for one of the least-tested categories. "
        "The fingerprint MUST start with the category letter (e.g. 'B_busy_monday')."
    )
    data, err = await _chat_json(CASE_DESIGNER_SYSTEM, user, max_tokens=1500)
    if err:
        return {"_error": err}
    return data


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
    data, err = await _chat_json(CRITIC_SYSTEM, user, max_tokens=1400)
    if err:
        return {"_error": err, "verdict": "fail", "viability_score": 0, "executive_summary": err}
    return data


async def synthesize_run(
    *,
    cases: list[dict],
    vision: str = PRODUCTION_MANAGER_VISION,
) -> Optional[dict]:
    user = f"Vision:\n{vision}\n\nCase results:\n{json.dumps(cases, default=str, indent=2)}"
    data, err = await _chat_json(SYNTHESIZER_SYSTEM, user, max_tokens=900)
    if err:
        return {"overall_assessment": err, "top_bugs": [err], "recommended_cursor_tasks": []}
    return data

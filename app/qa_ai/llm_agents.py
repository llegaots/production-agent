"""LLM personas for AI QA: case designer, schedule critic, run synthesizer."""
from __future__ import annotations

import json
from typing import Any, Optional

from ..llm import llm, safe_json
from ..vision import PRODUCTION_MANAGER_VISION

CASE_DESIGNER_SYSTEM = """You are a veteran West Island (Montreal) window cleaning production manager.
You design one REALISTIC test scenario at a time for ProductionAgent scheduling software.
We do residential and commercial window cleaning, gutter cleaning, pressure washing, and solar panels.
We do NOT do high-rise or rope-access work.

Output ONLY raw JSON. Never use markdown fences. Start with `{`, end with `}`.

══════════════════════════════════════════════════════════════════
THEME — you will be told which themes are already covered. Pick the next uncovered one.
Available themes (in suggested order):
  rain_day             — full day rained out, reschedule all affected jobs
  crew_fill            — pack idle crew days, "fill the trucks Monday"
  geo_routing          — tighten geographic clustering, cut cross-zone drive time
  equipment_conflict   — two crews need the one scissor-lift or pressure washer same day
  date_window          — client date constraint respected or violated
  balanced_workload    — one crew overloaded while another is idle
  revenue_priority     — high-value job deferred while low-value job lands

Record the theme you chose in the "theme" field.

══════════════════════════════════════════════════════════════════
TEST JOBS — define the jobs the scenario needs.

  "id"               — short slug like "job_001" (stored as qa_job_001 in Supabase)
  "service_type"     — window_cleaning | gutter_cleaning | pressure_washing | solar_panel_cleaning
  "address"          — MUST include street number, city, QC, and postal code
                       (e.g. "200 Saint-Louis Ave, Pointe-Claire QC H9R 2A1").
                       GeoCluster + Google Geocoding verify lat/lng — NEVER include lat/lng in JSON.
                       Use distinct cities: Pointe-Claire, Beaconsfield, Kirkland, Dorval, etc.
  "estimated_minutes"— window residential 60–180 min, gutter 90–240 min, pressure wash 90–180 min
  "difficulty"       — 1–5
  "required_skills"  — from: ladder_cert, lift_operator, pressure_wash, glass_restoration
  "required_equipment"— from: ladder_28, ladder_32, pressure_washer, water_fed_pole, scissor_lift, van
  "earliest_date"    — must be 2026-07-06 to 2026-07-10
  "latest_date"      — must be 2026-07-06 to 2026-07-10
  "price"            — $100–$1500

CREW CAPABILITIES:
  crew_alpha — ladder_cert, pressure_wash → has: pressure_washer, water_fed_pole, ladder_28, van
  crew_bravo — ladder_cert, lift_operator, pressure_wash, glass_restoration → has: pressure_washer, water_fed_pole, scissor_lift, ladder_28, ladder_32, van
  crew_delta — ladder_cert, pressure_wash → has: pressure_washer, water_fed_pole, ladder_28, van
  (crew_charlie does rope access — we don't use them)

Only assign skills/equipment that at least one of alpha/bravo/delta can cover.
Keep to 2–4 test jobs per scenario. test_jobs is REQUIRED — do not reference seed job IDs (job_W*, job_G*, etc.).

══════════════════════════════════════════════════════════════════
STEPS — the actions the executor will run in order:
  {"action": "plan", "scheduling_mode": "geo_first|crew_fill|balanced|revenue_priority"}
  {"action": "reorganize", "instruction": "owner chat text"}
  {"action": "reschedule", "job_id": "EXACT_ID_FROM_TEST_JOBS", "reason": "...", "preferred_day": "2026-07-08"}

The reschedule job_id MUST match one of your test_jobs ids exactly.
Use at most 2 steps — keep it focused.

══════════════════════════════════════════════════════════════════
JSON SCHEMA:
{
  "fingerprint": "theme_short_slug",
  "theme": "rain_day | crew_fill | geo_routing | equipment_conflict | date_window | balanced_workload | revenue_priority",
  "title": "one line",
  "persona_story": "1-2 sentences as the owner",
  "test_jobs": [ { "id": "job_001", "service_type": "...", "address": "...", ... } ],
  "steps": [ ... ],
  "what_good_looks_like": "specific observable outcome"
}"""

CRITIC_SYSTEM = """You are the same veteran window cleaning operator — brutally practical, not polite.
You are reviewing a DRAFT weekly schedule produced by software. Your job is to decide if you would actually
run this week in the field, or reject it.

CRITICAL RULES:
- The schedule contains ONLY qa_* test job IDs for this scenario (e.g. qa_job_001).
- NEVER mention seed/demo IDs like job_W05, job_W11, job_G05, job_H02, job_P01 — they are NOT in this test.
- Evaluate using ONLY job IDs listed in allowed_job_ids or shown in crew_days stops.
- If the schedule is empty — critical failure.

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
      "job_id": "qa_job_001",
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
    covered_themes: list[str] | None = None,
) -> Optional[dict]:
    covered = covered_themes or []

    all_themes = [
        "rain_day", "crew_fill", "geo_routing",
        "equipment_conflict", "date_window",
        "balanced_workload", "revenue_priority",
    ]
    uncovered = [t for t in all_themes if t not in covered]
    next_theme = uncovered[0] if uncovered else "geo_routing"

    user = (
        f"Case {case_index + 1}.\n\n"
        f"Themes already covered (DO NOT repeat): {json.dumps(covered)}\n"
        f"Themes not yet tested: {json.dumps(uncovered)}\n"
        f"Design a scenario for theme: \"{next_theme}\"\n\n"
        f"Fingerprints already in registry (avoid exact duplicates): {json.dumps(succeeded_fingerprints[:20])}\n"
        f"Failed this run (avoid repeating): "
        f"{json.dumps([f.get('fingerprint') for f in failed_this_run])}\n"
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
    test_jobs = case.get("test_jobs") or []
    id_map = {
        str(j.get("id") or j.get("job_id")): (
            j.get("id") if str(j.get("id", "")).startswith("qa_")
            else f"qa_{j.get('id') or j.get('job_id')}"
        )
        for j in test_jobs
        if j.get("id") or j.get("job_id")
    }
    user = (
        f"Test case: {json.dumps(case, default=str)}\n"
        f"Iteration: {iteration}\n"
    )
    if id_map:
        user += (
            f"Job ID mapping (designer id → persisted id in schedule): "
            f"{json.dumps(id_map)}\n"
        )
    user += f"Schedule under review:\n{json.dumps(schedule_context, default=str, indent=2)}\n"
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

"""Natural-language intake → structured job draft."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from anthropic import Anthropic

from app.config import get_settings
from app.specialists.schemas import IntakeParseInput, ParserMode, StructuredJobDraft

_DAY_NAMES = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_SERVICE_HINTS = {
    "window": "window_cleaning",
    "pressure": "pressure_washing",
    "gutter": "gutter_cleaning",
    "solar": "solar_panel_cleaning",
    "high rise": "high_rise",
    "high-rise": "high_rise",
}


def _reference_date(inp: IntakeParseInput) -> date:
    return inp.reference_date or date.today()


def _extract_client_name(text: str) -> str:
    patterns = [
        r"(?:for|with)\s+(?:Mrs\.?|Mr\.?|Ms\.?|Dr\.?)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(Mrs\.?|Mr\.?|Ms\.?)\s+([A-Z][a-z]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = [g for g in match.groups() if g]
            if len(groups) == 2 and groups[0].lower().startswith(("mr", "mrs", "ms", "dr")):
                return f"{groups[0].rstrip('.')}. {groups[1]}".strip()
            return groups[-1].strip()
    return "Unknown Client"


def _extract_weekday(text: str) -> int | None:
    lower = text.lower()
    for token, dow in _DAY_NAMES.items():
        if re.search(rf"\b{token}s?\b", lower):
            return dow
    return None


def _extract_service_type(text: str) -> str:
    lower = text.lower()
    for hint, stype in _SERVICE_HINTS.items():
        if hint in lower:
            return stype
    if "recurring" in lower or "service" in lower:
        return "window_cleaning"
    return "window_cleaning"


def _is_recurring(text: str) -> bool:
    return bool(re.search(r"\b(recurring|weekly|every\s+week|standing)\b", text, re.I))


def parse_intake_rule(inp: IntakeParseInput) -> StructuredJobDraft:
    text = inp.raw_text.strip()
    ref = _reference_date(inp)
    client_name = _extract_client_name(text)
    dow = _extract_weekday(text)
    recurring = _is_recurring(text)
    service_type = _extract_service_type(text)

    # Next occurrence of preferred weekday within ~2 weeks
    earliest = ref
    if dow is not None:
        days_ahead = (dow - ref.weekday()) % 7
        if days_ahead == 0 and not recurring:
            days_ahead = 7
        earliest = ref + timedelta(days=days_ahead or 0)

    recurrence_rule = ""
    if recurring and dow is not None:
        day_label = [k for k, v in _DAY_NAMES.items() if v == dow and len(k) > 3][0].title()
        recurrence_rule = f"weekly:{day_label}"
    elif recurring:
        recurrence_rule = "weekly"

    notes_parts = [f"Intake: {text}"]
    if recurrence_rule:
        notes_parts.append(f"Recurrence: {recurrence_rule}")

    return StructuredJobDraft(
        client_name=client_name,
        service_type=service_type,  # type: ignore[arg-type]
        address="",
        earliest_date=earliest,
        latest_date=earliest + timedelta(days=30),
        notes=" | ".join(notes_parts),
        recurrence_rule=recurrence_rule,
        preferred_day_of_week=dow,
        required_skills=["residential"],
    )


SYSTEM_PROMPT = """You parse dispatcher intake for a window-cleaning company.

Return ONLY valid JSON (no markdown):
{
  "client_name": "Mrs. Chen",
  "service_type": "window_cleaning|pressure_washing|gutter_cleaning|solar_panel_cleaning|high_rise",
  "address": "optional street address or empty string",
  "estimated_minutes": 90,
  "difficulty": 2,
  "earliest_date": "YYYY-MM-DD",
  "latest_date": "YYYY-MM-DD",
  "recurrence_rule": "weekly:Tuesday or empty",
  "preferred_day_of_week": 0-6 or null,
  "notes": "short summary"
}

Map weekdays: Monday=0 … Sunday=6. Infer recurring from phrases like 'recurring' or 'every Tuesday'."""


def _parse_llm_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text.strip())
    if not match:
        raise ValueError("No JSON in LLM intake response")
    return json.loads(match.group())


def parse_intake_llm(inp: IntakeParseInput) -> StructuredJobDraft:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return parse_intake_rule(inp)

    ref = _reference_date(inp)
    client = Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {"raw_text": inp.raw_text, "reference_date": ref.isoformat()},
                    indent=2,
                ),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    data = _parse_llm_json(text)
    rule_fallback = parse_intake_rule(inp)
    return StructuredJobDraft(
        client_name=str(data.get("client_name") or rule_fallback.client_name),
        service_type=data.get("service_type") or rule_fallback.service_type,
        address=str(data.get("address") or rule_fallback.address),
        lat=rule_fallback.lat,
        lng=rule_fallback.lng,
        estimated_minutes=int(data.get("estimated_minutes", rule_fallback.estimated_minutes)),
        difficulty=int(data.get("difficulty", rule_fallback.difficulty)),
        required_skills=rule_fallback.required_skills,
        earliest_date=date.fromisoformat(data["earliest_date"])
        if data.get("earliest_date")
        else rule_fallback.earliest_date,
        latest_date=date.fromisoformat(data["latest_date"])
        if data.get("latest_date")
        else rule_fallback.latest_date,
        notes=str(data.get("notes") or rule_fallback.notes),
        recurrence_rule=str(data.get("recurrence_rule") or rule_fallback.recurrence_rule),
        preferred_day_of_week=data.get("preferred_day_of_week", rule_fallback.preferred_day_of_week),
    )


def parse_intake_request(inp: IntakeParseInput) -> tuple[StructuredJobDraft, ParserMode]:
    if inp.use_llm and get_settings().anthropic_api_key:
        try:
            return parse_intake_llm(inp), "llm"
        except Exception:
            return parse_intake_rule(inp), "hybrid"
    return parse_intake_rule(inp), "rule"

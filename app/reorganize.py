"""Parse owner chat instructions and apply schedule reorganization."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .scheduling_prefs import SchedulingMode, parse_mode


@dataclass
class ReorganizeIntent:
    instruction: str
    scheduling_mode: SchedulingMode
    job_id: Optional[str] = None
    target_day: Optional[date] = None
    reason: str = "Owner requested schedule change via chat"
    is_emergency: bool = False
    emergency_keywords: list[str] = field(default_factory=list)


_JOB_RE = re.compile(r"\b(job_[\w-]+)\b", re.I)
_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
_MODE_RE = re.compile(
    r"(crew\s*fill|fill\s*(?:up\s*)?(?:the\s*)?crews|pack\s*crews|utilization|geo\s*first|"
    r"minimize\s*drive|location\s*first|proximity|balanced|balance|revenue|priority)",
    re.I,
)

# Emergency patterns — any match escalates to CREW_FILL and first available slot.
_EMERGENCY_PATTERNS = re.compile(
    r"\b(urgent|today|asap|emergency|flood|flooding|water\s+damage|water\s+leak|"
    r"right\s+now|immediately|lose\s+(?:the\s+)?contract|client\s+threatening|"
    r"losing\s+client|need\s+crew\s+now|8k|10k|\$\d+k?\s+contract)\b",
    re.I,
)


def _parse_day_token(token: str, week_start: date) -> Optional[date]:
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    t = token.lower()
    if t not in names:
        return None
    idx = names.index(t)
    return week_start.fromordinal(week_start.toordinal() + idx) if idx < 5 else None


def parse_reorganize_instruction(text: str, week_start: date) -> ReorganizeIntent:
    """Extract scheduling preference and optional single-job move from natural language.

    Emergency detection: if the text contains urgency keywords (URGENT, TODAY, flood,
    water damage, contract loss, etc.), the intent is flagged as emergency, scheduling
    mode is escalated to CREW_FILL (pack available capacity), and the reason is enriched
    with the detected keywords so the executor can prioritise the affected job.
    """
    lower = text.lower()

    # ── Emergency detection (checked before mode) ────────────────────────────
    emergency_matches = _EMERGENCY_PATTERNS.findall(lower)
    is_emergency = bool(emergency_matches)

    # ── Scheduling mode ───────────────────────────────────────────────────────
    if is_emergency:
        # Emergencies always pack capacity to find the earliest possible slot.
        mode = SchedulingMode.CREW_FILL
    elif "fill" in lower and "crew" in lower:
        mode = SchedulingMode.CREW_FILL
    elif re.search(r"minimize\s*drive|geo\s*first|location\s*first|proximity", lower):
        mode = SchedulingMode.GEO_FIRST
    elif re.search(r"balanced|balance", lower):
        mode = SchedulingMode.BALANCED
    elif re.search(r"revenue|priority|high.value|urgent.job", lower):
        mode = SchedulingMode.REVENUE_PRIORITY
    else:
        m = _MODE_RE.search(lower)
        mode = parse_mode(m.group(1)) if m else SchedulingMode.GEO_FIRST

    # ── Job ID extraction ─────────────────────────────────────────────────────
    job_id = None
    jm = _JOB_RE.search(text)
    if jm:
        job_id = jm.group(1).lower().replace("job-", "job_")

    # ── Target day extraction ─────────────────────────────────────────────────
    target_day = None
    dm = _DAY_RE.search(lower)
    if dm:
        target_day = _parse_day_token(dm.group(1), week_start)

    # Emergency with no explicit day → target the earliest slot (week_start)
    if is_emergency and target_day is None:
        target_day = week_start

    reason = text.strip()[:500] or "Owner requested schedule change via chat"
    if is_emergency:
        kw_str = ", ".join(dict.fromkeys(k.strip() for k in emergency_matches))
        reason = f"EMERGENCY ({kw_str}): {reason}"

    return ReorganizeIntent(
        instruction=text,
        scheduling_mode=mode,
        job_id=job_id,
        target_day=target_day,
        reason=reason,
        is_emergency=is_emergency,
        emergency_keywords=list(dict.fromkeys(k.strip() for k in emergency_matches)),
    )

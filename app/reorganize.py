"""Parse owner chat instructions and apply schedule reorganization."""
from __future__ import annotations

import re
from dataclasses import dataclass
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


_JOB_RE = re.compile(r"\b(job_[\w-]+)\b", re.I)
_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
_MODE_RE = re.compile(
    r"(crew\s*fill|fill\s*(?:up\s*)?(?:the\s*)?crews|pack\s*crews|utilization|geo\s*first|"
    r"minimize\s*drive|location\s*first|proximity|balanced|balance)",
    re.I,
)


def _parse_day_token(token: str, week_start: date) -> Optional[date]:
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    t = token.lower()
    if t not in names:
        return None
    idx = names.index(t)
    return week_start.fromordinal(week_start.toordinal() + idx) if idx < 5 else None


_EMERGENCY_RE = re.compile(
    r"\b(urgent|today|emergency|flood|asap)\b|water\s+damage",
    re.I,
)


def parse_reorganize_instruction(text: str, week_start: date) -> ReorganizeIntent:
    """Extract scheduling preference and optional single-job move from natural language."""
    lower = text.lower()

    # Emergency keywords take highest priority: override mode to CREW_FILL and
    # target the earliest available slot (week_start = Monday of current week).
    is_emergency = bool(_EMERGENCY_RE.search(lower))

    if is_emergency:
        mode = SchedulingMode.CREW_FILL
    elif "fill" in lower and "crew" in lower:
        mode = SchedulingMode.CREW_FILL
    elif re.search(r"minimize\s*drive|geo\s*first|location\s*first|proximity", lower):
        mode = SchedulingMode.GEO_FIRST
    elif re.search(r"balanced|balance", lower):
        mode = SchedulingMode.BALANCED
    else:
        m = _MODE_RE.search(lower)
        if m:
            mode = parse_mode(m.group(1))
        else:
            mode = SchedulingMode.GEO_FIRST

    job_id = None
    jm = _JOB_RE.search(text)
    if jm:
        job_id = jm.group(1).lower().replace("job-", "job_")

    target_day: Optional[date] = None
    if is_emergency:
        # Force the job to the earliest slot in the current week
        target_day = week_start
    else:
        dm = _DAY_RE.search(lower)
        if dm:
            target_day = _parse_day_token(dm.group(1), week_start)

    reason = text.strip()[:500] or "Owner requested schedule change via chat"
    return ReorganizeIntent(
        instruction=text,
        scheduling_mode=mode,
        job_id=job_id,
        target_day=target_day,
        reason=reason,
    )

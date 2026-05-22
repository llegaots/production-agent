"""Parse owner chat instructions and apply schedule reorganization."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .scheduling_prefs import SchedulingMode, parse_mode


@dataclass
class ReorganizeIntent:
    instruction: str
    scheduling_mode: SchedulingMode
    job_id: Optional[str] = None
    target_day: Optional[date] = None
    reason: str = "Owner requested schedule change via chat"
    # When the owner says "reschedule to next week" this is set so the
    # executor can extend the job's availability window accordingly.
    deferred_to_next_week: bool = False
    # Jobs the owner explicitly named for deferral (batch reschedule)
    deferred_job_ids: list[str] = field(default_factory=list)
    # Safety-first override: skip non-critical work to protect crew
    safety_priority: bool = False


_JOB_RE = re.compile(r"\b(job_[\w-]+)\b", re.I)
_ALL_JOBS_RE = re.compile(r"\b(job_[\w-]+)\b", re.I)
_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
_MODE_RE = re.compile(
    r"(crew\s*fill|fill\s*(?:up\s*)?(?:the\s*)?crews|pack\s*crews|utilization|geo\s*first|"
    r"minimize\s*drive|location\s*first|proximity|balanced|balance)",
    re.I,
)
_NEXT_WEEK_RE = re.compile(r"\bnext\s+week\b", re.I)
_RESCHEDULE_RE = re.compile(r"\breschedul\w*\b", re.I)
_SAFETY_RE = re.compile(r"\bsafety\s*(?:first|priority|concern)?\b", re.I)


def _parse_day_token(token: str, week_start: date) -> Optional[date]:
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    t = token.lower()
    if t not in names:
        return None
    idx = names.index(t)
    return week_start.fromordinal(week_start.toordinal() + idx) if idx < 5 else None


def parse_reorganize_instruction(text: str, week_start: date) -> ReorganizeIntent:
    """Extract scheduling preference and job-move directives from natural language.

    Handles:
    - Scheduling mode keywords (crew fill, geo first, balanced)
    - Single job + target day (``job_003 on Thursday``)
    - "next week" deferral: sets ``deferred_to_next_week=True`` on the intent
    - Multiple job IDs: ``job_H01`` and ``job_H02`` → ``deferred_job_ids``
    - Safety keywords: ``safety first`` → ``safety_priority=True``
    """
    lower = text.lower()
    mode = SchedulingMode.GEO_FIRST
    if "fill" in lower and "crew" in lower:
        mode = SchedulingMode.CREW_FILL
    elif re.search(r"minimize\s*drive|geo\s*first|location\s*first|proximity", lower):
        mode = SchedulingMode.GEO_FIRST
    elif re.search(r"balanced|balance", lower):
        mode = SchedulingMode.BALANCED
    else:
        m = _MODE_RE.search(lower)
        if m:
            mode = parse_mode(m.group(1))

    # Collect all named job IDs (there can be multiple)
    all_job_ids = [
        m.group(1).lower().replace("job-", "job_")
        for m in _ALL_JOBS_RE.finditer(text)
    ]
    job_id = all_job_ids[0] if all_job_ids else None

    target_day: Optional[date] = None
    dm = _DAY_RE.search(lower)
    if dm:
        target_day = _parse_day_token(dm.group(1), week_start)

    # "next week" deferral: target_day becomes next Monday if no explicit day given
    deferred_to_next_week = bool(_NEXT_WEEK_RE.search(lower))
    if deferred_to_next_week and target_day is None:
        # Find the Monday of the following week
        target_day = week_start + timedelta(weeks=1)

    # Safety priority flag
    safety_priority = bool(_SAFETY_RE.search(lower))

    # Jobs named for batch deferral: all job IDs after the first, when the
    # instruction contains "reschedule" / "move" and "next week"
    deferred_job_ids: list[str] = []
    if (deferred_to_next_week or bool(_RESCHEDULE_RE.search(lower))) and len(all_job_ids) > 1:
        deferred_job_ids = all_job_ids[1:]

    reason = text.strip()[:500] or "Owner requested schedule change via chat"
    return ReorganizeIntent(
        instruction=text,
        scheduling_mode=mode,
        job_id=job_id,
        target_day=target_day,
        reason=reason,
        deferred_to_next_week=deferred_to_next_week,
        deferred_job_ids=deferred_job_ids,
        safety_priority=safety_priority,
    )

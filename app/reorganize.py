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
    # Parsed start time for early-start scheduling (e.g. "7am" → "07:00")
    start_time: Optional[str] = None
    reason: str = "Owner requested schedule change via chat"
    is_emergency: bool = False
    emergency_keywords: list[str] = field(default_factory=list)
    # True when the target_day is in the NEXT calendar week (owner said "next Monday" etc.)
    target_is_next_week: bool = False


_JOB_RE = re.compile(r"\b(job_[\w-]+)\b", re.I)
_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
# "next Monday", "next week Thursday", etc.
_NEXT_WEEK_DAY_RE = re.compile(
    r"\bnext\s+(monday|tuesday|wednesday|thursday|friday)\b", re.I
)
# "next week" without a specific day
_NEXT_WEEK_RE = re.compile(r"\bnext\s+week\b", re.I)
_MODE_RE = re.compile(
    r"(crew\s*fill|fill\s*(?:up\s*)?(?:the\s*)?crews|pack\s*crews|utilization|geo\s*first|"
    r"minimize\s*drive|location\s*first|proximity|balanced|balance|revenue|priority)",
    re.I,
)
# 7am / 7:00 / 07:00 am / early start / compress
_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b"
    r"|\b(\d{2}):(\d{2})\b"
    r"|\b(early\s*start|compress)\b",
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


def _extract_start_time(text: str) -> Optional[str]:
    """Return a HH:MM string from patterns like '7am', '07:00', 'early start', 'compress'."""
    m = _TIME_RE.search(text)
    if not m:
        return None
    # Group 6: "early start" or "compress" keywords → default 07:00
    if m.group(6):
        return "07:00"
    # Groups 1-3: 7am / 7:30pm style
    if m.group(1) is not None:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        period = (m.group(3) or "").lower()
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    # Groups 4-5: HH:MM 24h
    if m.group(4) is not None:
        return f"{m.group(4)}:{m.group(5)}"
    return None


def parse_reorganize_instruction(text: str, week_start: date) -> ReorganizeIntent:
    """Extract scheduling preference and optional single-job move from natural language.

    Emergency detection: if the text contains urgency keywords (URGENT, TODAY, flood,
    water damage, contract loss, etc.), the intent is flagged as emergency, scheduling
    mode is escalated to CREW_FILL (pack available capacity), and the reason is enriched
    with the detected keywords so the executor can prioritise the affected job.

    Next-week detection: if the text contains "next Monday", "next week", or similar,
    target_day is set to the matching day in the FOLLOWING calendar week and
    target_is_next_week is set to True so the executor can extend the reschedule window.
    """
    lower = text.lower()

    # ── Emergency detection (checked before mode) ────────────────────────────
    emergency_matches = _EMERGENCY_PATTERNS.findall(lower)
    is_emergency = bool(emergency_matches)

    # ── Scheduling mode ───────────────────────────────────────────────────────
    if is_emergency:
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
    target_is_next_week = False

    # Check "next Monday" / "next Thursday" etc. BEFORE generic day match
    nwm = _NEXT_WEEK_DAY_RE.search(lower)
    if nwm:
        day_name = nwm.group(1)
        next_week_start = week_start + timedelta(days=7)
        target_day = _parse_day_token(day_name, next_week_start)
        target_is_next_week = True
    else:
        # Check plain "next week" without a day → use same weekday as week_start (Monday)
        nw = _NEXT_WEEK_RE.search(lower)
        if nw:
            # Check if a specific day also appears
            dm = _DAY_RE.search(lower)
            if dm:
                next_week_start = week_start + timedelta(days=7)
                target_day = _parse_day_token(dm.group(1), next_week_start)
            else:
                target_day = week_start + timedelta(days=7)  # next Monday
            target_is_next_week = True
        else:
            dm = _DAY_RE.search(lower)
            if dm:
                target_day = _parse_day_token(dm.group(1), week_start)

    # Emergency with no explicit day → target the earliest slot (week_start)
    if is_emergency and target_day is None:
        target_day = week_start

    # ── Start time extraction ─────────────────────────────────────────────────
    start_time = _extract_start_time(lower)

    reason = text.strip()[:500] or "Owner requested schedule change via chat"
    if is_emergency:
        kw_str = ", ".join(dict.fromkeys(k.strip() for k in emergency_matches))
        reason = f"EMERGENCY ({kw_str}): {reason}"

    return ReorganizeIntent(
        instruction=text,
        scheduling_mode=mode,
        job_id=job_id,
        target_day=target_day,
        start_time=start_time,
        reason=reason,
        is_emergency=is_emergency,
        emergency_keywords=list(dict.fromkeys(k.strip() for k in emergency_matches)),
        target_is_next_week=target_is_next_week,
    )

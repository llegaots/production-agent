"""Track QA scenarios that have already been tested so they are not repeated.

Each entry records:
  fingerprint  — unique slug (used for exact-duplicate detection)
  theme        — human-readable topic, e.g. "rain_day", "crew_fill", "equipment_conflict"
  title        — one-line description shown in the UI
  run_id       — the QA run that produced this result
  viability_score — critic score (0-100)
  succeeded_at — ISO timestamp

The designer prompt receives both the fingerprint list (exact dedup) AND
the theme list (semantic dedup) so it can skip covered territory.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..audit_log import REPORTS_DIR

REGISTRY_PATH = REPORTS_DIR / "qa_succeeded_cases.json"


def load_succeeded_cases() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return list(data.get("cases") or [])
    except Exception:
        return []


def save_succeeded_case(
    *,
    fingerprint: str,
    title: str,
    run_id: str,
    viability_score: int,
    theme: str = "",
) -> None:
    cases = load_succeeded_cases()
    if any(c.get("fingerprint") == fingerprint for c in cases):
        return
    cases.append(
        {
            "fingerprint": fingerprint,
            "theme": theme or _guess_theme(fingerprint, title),
            "title": title,
            "run_id": run_id,
            "viability_score": viability_score,
            "succeeded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps({"cases": cases[-200:]}, indent=2), encoding="utf-8"
    )


def _guess_theme(fingerprint: str, title: str) -> str:
    """Best-effort theme from fingerprint/title when not explicitly set."""
    combined = (fingerprint + " " + title).lower()
    for kw, theme in [
        ("rain", "rain_day"),
        ("weather", "rain_day"),
        ("flood", "rain_day"),
        ("fill", "crew_fill"),
        ("utiliz", "crew_fill"),
        ("pack", "crew_fill"),
        ("geo", "geo_routing"),
        ("route", "geo_routing"),
        ("drive", "geo_routing"),
        ("equip", "equipment_conflict"),
        ("conflict", "equipment_conflict"),
        ("ladder", "equipment_conflict"),
        ("skill", "skill_gap"),
        ("cert", "skill_gap"),
        ("date", "date_window"),
        ("window", "date_window"),
        ("revenue", "revenue_priority"),
        ("priority", "revenue_priority"),
        ("balance", "balanced_workload"),
        ("spread", "balanced_workload"),
    ]:
        if kw in combined:
            return theme
    return "other"


def fingerprints_for_prompt() -> list[str]:
    return [c.get("fingerprint", "") for c in load_succeeded_cases() if c.get("fingerprint")]


def themes_covered() -> list[str]:
    """Distinct themes that already have at least one passing case."""
    seen: list[str] = []
    for c in load_succeeded_cases():
        t = c.get("theme", "")
        if t and t not in seen:
            seen.append(t)
    return seen


def seed_theme(theme: str, title: str) -> None:
    """Mark a theme as already covered without an actual run (used to skip topics)."""
    cases = load_succeeded_cases()
    fp = f"seeded_{theme}"
    if any(c.get("fingerprint") == fp for c in cases):
        return
    cases.append({
        "fingerprint": fp,
        "theme": theme,
        "title": title,
        "run_id": "seeded",
        "viability_score": 100,
        "succeeded_at": datetime.now(timezone.utc).isoformat(),
    })
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps({"cases": cases[-200:]}, indent=2), encoding="utf-8"
    )

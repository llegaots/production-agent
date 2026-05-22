"""Track QA cases that already passed so the designer does not repeat them."""
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
) -> None:
    cases = load_succeeded_cases()
    if any(c.get("fingerprint") == fingerprint for c in cases):
        return
    cases.append(
        {
            "fingerprint": fingerprint,
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


def fingerprints_for_prompt() -> list[str]:
    return [c.get("fingerprint", "") for c in load_succeeded_cases() if c.get("fingerprint")]

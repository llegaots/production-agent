#!/usr/bin/env python3
"""
Normalize qa_job_* rows so OR-Tools can assign them to crew_alpha/bravo/delta.

Fixes:
- ladder_32 -> ladder_28 (crews carry ladder_28)
- seed-crew / golden crews excluded at run time in UI; skills stay ladder_cert / pressure_wash
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools._db import tools_db  # noqa: E402

# Equipment kinds that exist on crew_alpha / crew_bravo (see equipment + crew_equipment tables)
VALID_EQUIPMENT = {
    "ladder_28",
    "van",
    "pressure_washer",
    "water_fed_pole",
    "extension_pole",
    "scissor_lift",
}

EQUIPMENT_ALIASES = {
    "ladder_32": "ladder_28",
    "ladder": "ladder_28",
    "pressure_wash": "pressure_washer",
}


def normalize_equipment(kinds: list[str]) -> list[str]:
    out: list[str] = []
    for k in kinds or []:
        k = EQUIPMENT_ALIASES.get(k, k)
        if k in VALID_EQUIPMENT and k not in out:
            out.append(k)
    return out or ["ladder_28", "van"]


def normalize_skills(skills: list[str], service_type: str) -> list[str]:
    s = list(skills or [])
    if not s:
        if service_type == "pressure_washing":
            return ["pressure_wash"]
        return ["ladder_cert"]
    mapped = []
    for sk in s:
        if sk == "pressure_washer":
            mapped.append("pressure_wash")
        elif sk in ("residential", "commercial", "solar", "high_rise", "rope_access"):
            mapped.append("ladder_cert")
        else:
            mapped.append(sk)
    return list(dict.fromkeys(mapped))


def main() -> int:
    db = tools_db()
    rows = db.table("jobs").select("*").like("id", "qa_job_%").execute().data or []
    updated = 0
    for row in rows:
        new_skills = normalize_skills(row.get("required_skills") or [], row.get("service_type", ""))
        new_equip = normalize_equipment(list(row.get("required_equipment") or []))
        # lift_operator jobs need bravo's scissor_lift — keep skill, ensure equipment
        if "lift_operator" in new_skills and "scissor_lift" not in new_equip:
            new_equip = list(dict.fromkeys([*new_equip, "scissor_lift", "van"]))
        patch = {
            "required_skills": new_skills,
            "required_equipment": new_equip,
        }
        if patch["required_skills"] != (row.get("required_skills") or []) or patch[
            "required_equipment"
        ] != (row.get("required_equipment") or []):
            db.table("jobs").update(patch).eq("id", row["id"]).execute()
            updated += 1
            print(f"fixed {row['id']}: skills={new_skills} equipment={new_equip}")
    print(f"Done — updated {updated} / {len(rows)} qa_job rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

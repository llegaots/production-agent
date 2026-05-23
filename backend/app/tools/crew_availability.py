from __future__ import annotations

from app.tools._db import tools_db
from app.tools.schemas import (
    CrewAvailabilityRow,
    GetCrewAvailabilityInput,
    GetCrewAvailabilityOutput,
)


def get_crew_availability(inp: GetCrewAvailabilityInput) -> GetCrewAvailabilityOutput:
    """Crew shift availability for a date (DB overrides + crew defaults)."""
    db = tools_db()
    q = db.table("crews").select("id, name, skills, daily_minutes")
    if inp.crew_ids:
        q = q.in_("id", inp.crew_ids)
    crews = q.execute().data or []

    overrides = (
        db.table("crew_availability")
        .select("*")
        .eq("available_date", inp.target_date.isoformat())
        .execute()
        .data
        or []
    )
    by_crew = {row["crew_id"]: row for row in overrides}

    rows: list[CrewAvailabilityRow] = []
    for crew in crews:
        ov = by_crew.get(crew["id"])
        daily = int(crew.get("daily_minutes") or 480)
        if ov:
            rows.append(
                CrewAvailabilityRow(
                    crew_id=crew["id"],
                    crew_name=crew["name"],
                    is_available=bool(ov["is_available"]),
                    shift_start_minute=int(ov["shift_start_minute"]),
                    shift_end_minute=int(ov["shift_end_minute"]),
                    unavailable_reason=ov.get("unavailable_reason") or "",
                    skills=list(crew.get("skills") or []),
                )
            )
        else:
            rows.append(
                CrewAvailabilityRow(
                    crew_id=crew["id"],
                    crew_name=crew["name"],
                    is_available=True,
                    shift_start_minute=0,
                    shift_end_minute=daily,
                    skills=list(crew.get("skills") or []),
                )
            )

    return GetCrewAvailabilityOutput(target_date=inp.target_date, crews=rows)

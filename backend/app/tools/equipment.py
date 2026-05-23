from __future__ import annotations

from collections import defaultdict

from app.tools._db import tools_db
from app.tools.schemas import (
    CheckEquipmentInput,
    CheckEquipmentOutput,
    EquipmentConflict,
)


def check_equipment(inp: CheckEquipmentInput) -> CheckEquipmentOutput:
    """Verify global inventory and crew assignments cover job equipment needs."""
    db = tools_db()
    jobs = (
        db.table("jobs")
        .select("id, required_equipment")
        .in_("id", inp.job_ids)
        .execute()
        .data
        or []
    )
    if len(jobs) != len(inp.job_ids):
        raise ValueError("One or more jobs not found")

    inv_rows = db.table("equipment").select("kind, quantity").execute().data or []
    inventory: dict[str, int] = defaultdict(int)
    for row in inv_rows:
        inventory[row["kind"]] += int(row["quantity"])

    cq = db.table("crew_equipment").select("crew_id, equipment_id")
    if inp.crew_ids:
        cq = cq.in_("crew_id", inp.crew_ids)
    links = cq.execute().data or []
    equip_ids = list({link["equipment_id"] for link in links})
    equip_by_id: dict[str, str] = {}
    if equip_ids:
        eq_rows = db.table("equipment").select("id, kind").in_("id", equip_ids).execute().data or []
        equip_by_id = {r["id"]: r["kind"] for r in eq_rows}

    crew_equipment: dict[str, list[str]] = defaultdict(list)
    for link in links:
        kind = equip_by_id.get(link["equipment_id"])
        if kind:
            crew_equipment[link["crew_id"]].append(kind)

    conflicts: list[EquipmentConflict] = []
    for job in jobs:
        kinds = list(job.get("required_equipment") or [])
        for kind in kinds:
            if inventory.get(kind, 0) < 1:
                conflicts.append(
                    EquipmentConflict(
                        job_id=job["id"],
                        equipment_kind=kind,
                        reason=f"No inventory for {kind}",
                    )
                )
                continue
            if inp.crew_ids:
                any_crew = any(kind in crew_equipment.get(cid, []) for cid in inp.crew_ids)
                if not any_crew:
                    conflicts.append(
                        EquipmentConflict(
                            job_id=job["id"],
                            equipment_kind=kind,
                            reason=f"No listed crew carries {kind}",
                        )
                    )

    return CheckEquipmentOutput(
        ok=len(conflicts) == 0,
        conflicts=conflicts,
        inventory=dict(inventory),
        crew_equipment={k: sorted(set(v)) for k, v in crew_equipment.items()},
    )

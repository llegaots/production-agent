"""EquipmentAgent - validates equipment availability for each crew/day.

Anthropic pattern: **Parallelization (sectioning)**.

The supervisor runs this agent concurrently with TimeBudgetAgent because
they validate independent aspects of the same draft plan. Sectioning is
more reliable than asking one prompt to do both.

Each crew has a fixed equipment loadout. The agent flags any job that
requires equipment the assigned crew does not carry, and surfaces a clear
remediation (swap crews, reschedule day, or rent).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..models import EquipmentKind
from ..storage import store
from .base import Agent, AgentContext


class EquipmentAgent(Agent):
    name = "EquipmentAgent"

    async def run(self, ctx: AgentContext) -> None:
        draft = ctx.blackboard.get("draft_plan", [])
        jobs_by_id = {j.id: j for j in ctx.jobs}
        crews_by_id = {c.id: c for c in ctx.crews}

        await ctx.emit_tool(
            "equipment_check",
            "invoke",
            "Validating crew loadouts vs job requirements and daily equipment contention.",
            {"draft_entries": len(draft)},
        )
        await ctx.emit(self.name, "start", "Checking equipment loadouts per crew/day.")

        # equipment kinds available per crew (from store)
        crew_kinds: dict[str, set[EquipmentKind]] = {}
        for c in ctx.crews:
            kinds = set()
            for eid in c.equipment_ids:
                e = store.get_equipment(eid)
                if e:
                    kinds.add(e.kind)
            crew_kinds[c.id] = kinds

        conflicts: list[str] = []
        gaps: list[dict] = []

        # daily equipment uniqueness check (same kind can't be on two crews if quantity=1)
        per_day_equipment: dict[date, dict[EquipmentKind, list[str]]] = defaultdict(lambda: defaultdict(list))
        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            for eid in crew.equipment_ids:
                e = store.get_equipment(eid)
                if e:
                    per_day_equipment[entry["day"]][e.kind].append(crew.id)

        for day, kinds in per_day_equipment.items():
            for kind, crew_ids in kinds.items():
                if len(crew_ids) > 1:
                    # check actual stock for this kind
                    total = sum(eq.quantity for eq in store.list_equipment() if eq.kind == kind)
                    if len(crew_ids) > total:
                        conflicts.append(
                            f"On {day.isoformat()}, {len(crew_ids)} crews need {kind.value} but only {total} unit(s) exist."
                        )
                        await ctx.emit(
                            self.name,
                            "conflict",
                            f"Equipment contention on {day.isoformat()} for {kind.value} ({len(crew_ids)} crews need it).",
                        )

        # per-job equipment fit
        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            available = crew_kinds[crew.id]
            for job_id in entry["job_ids"]:
                job = jobs_by_id[job_id]
                missing = set(job.required_equipment) - available
                if missing:
                    gaps.append(
                        {
                            "job_id": job_id,
                            "crew_id": crew.id,
                            "day": entry["day"].isoformat(),
                            "missing": [m.value for m in missing],
                        }
                    )
                    await ctx.emit(
                        self.name,
                        "gap",
                        f"Job {job_id} on {crew.name}/{entry['day'].isoformat()} is missing: {', '.join(m.value for m in missing)}.",
                    )

        ctx.blackboard["equipment_conflicts"] = conflicts
        ctx.blackboard["equipment_gaps"] = gaps
        await ctx.emit(
            self.name,
            "done",
            f"Equipment check: {len(conflicts)} day-level conflicts, {len(gaps)} per-job gaps.",
        )

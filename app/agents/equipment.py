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

        # Track which jobs must be moved to unscheduled due to equipment conflicts.
        # We cannot silently return a schedule where a crew can't operate.
        conflict_deferred: list[str] = []

        for day, kinds in per_day_equipment.items():
            for kind, crew_ids in kinds.items():
                if len(crew_ids) > 1:
                    total = sum(eq.quantity for eq in store.list_equipment() if eq.kind == kind)
                    if len(crew_ids) > total:
                        shortage = len(crew_ids) - total
                        conflict_msg = (
                            f"On {day.isoformat()}, {len(crew_ids)} crews need {kind.value} "
                            f"but only {total} unit(s) exist — {shortage} crew(s) cannot operate."
                        )
                        conflicts.append(conflict_msg)
                        await ctx.emit(
                            self.name,
                            "conflict",
                            f"Equipment contention on {day.isoformat()} for {kind.value} "
                            f"({len(crew_ids)} crews, {total} unit(s)). "
                            "Deferring lowest-value jobs from conflicting crews.",
                        )
                        # Resolve: identify which crew-day entries on this day carry
                        # the contested equipment kind and defer jobs from the
                        # excess crew-days (lowest-revenue first).
                        conflicting_entries = [
                            e for e in draft
                            if e["day"] == day
                            and any(
                                store.get_equipment(eid) and store.get_equipment(eid).kind == kind
                                for eid in crews_by_id[e["crew_id"]].equipment_ids
                            )
                        ]
                        # Sort entries by total job revenue desc — keep highest-revenue
                        # entries, defer the rest.
                        conflicting_entries.sort(
                            key=lambda e: -sum(
                                (jobs_by_id.get(jid) and jobs_by_id[jid].price or 0)
                                for jid in e["job_ids"]
                            )
                        )
                        for excess_entry in conflicting_entries[total:]:
                            for jid in excess_entry["job_ids"]:
                                if jid not in conflict_deferred:
                                    conflict_deferred.append(jid)
                                    await ctx.emit(
                                        self.name,
                                        "defer",
                                        f"Job {jid} deferred: {kind.value} conflict on "
                                        f"{day.isoformat()} with crew {excess_entry['crew_id']}.",
                                    )
                            # Remove the deferred jobs from the draft entry.
                            excess_entry["job_ids"] = [
                                jid for jid in excess_entry["job_ids"]
                                if jid not in conflict_deferred
                            ]

        # Add conflict-deferred jobs to the unscheduled list so they appear
        # in the plan's unscheduled_job_ids rather than as ghost assignments.
        existing_unscheduled: list[str] = ctx.blackboard.get("unscheduled", [])
        ctx.blackboard["unscheduled"] = existing_unscheduled + conflict_deferred

        # per-job equipment fit
        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            available = crew_kinds[crew.id]
            for job_id in entry["job_ids"]:
                if job_id in conflict_deferred:
                    continue  # already handled above
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

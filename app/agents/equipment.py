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

        # --- attempt to resolve day-level equipment contention ---
        # For each conflicting (day, kind) pair, identify the crew-day with the
        # smallest job load and move it to the earliest alternative day that is
        # free of the same conflict.  This modifies draft in-place so that
        # TimeBudgetAgent (running in parallel) operates on a conflict-free plan.
        if conflicts:
            resolved_conflicts: list[str] = []
            all_days = sorted({e["day"] for e in draft})
            # Build the set of days present in the plan plus a few lookahead days
            from datetime import timedelta
            from .base import week_days
            max_day = max(all_days) if all_days else ctx.week_start
            extended_days = list(all_days) + [max_day + timedelta(days=i) for i in range(1, 6)]

            for day, kinds in per_day_equipment.items():
                for kind, crew_ids in kinds.items():
                    if len(crew_ids) <= 1:
                        continue
                    total_units = sum(eq.quantity for eq in store.list_equipment() if eq.kind == kind)
                    if len(crew_ids) <= total_units:
                        continue
                    # Find draft entries for these conflicting crew/days
                    conflict_entries = [
                        e for e in draft if e["day"] == day and e["crew_id"] in crew_ids
                    ]
                    if not conflict_entries:
                        continue
                    # Move the entry with the fewest job minutes to a later day
                    conflict_entries.sort(key=lambda e: sum(
                        jobs_by_id[j].estimated_minutes for j in e["job_ids"] if j in jobs_by_id
                    ))
                    to_move = conflict_entries[0]
                    moved = False
                    for alt_day in extended_days:
                        if alt_day == day or alt_day.weekday() >= 5:
                            continue
                        # Check no new conflict on alt_day for this kind
                        alt_crews_with_kind = per_day_equipment.get(alt_day, {}).get(kind, [])
                        alt_count = len(alt_crews_with_kind)
                        if alt_count < total_units:
                            # Check date windows for jobs in to_move
                            jobs_in_entry = [jobs_by_id[j] for j in to_move["job_ids"] if j in jobs_by_id]
                            if any(alt_day < j.earliest_date or alt_day > j.latest_date for j in jobs_in_entry):
                                continue
                            # Check crew capacity on alt_day
                            crew_obj = crews_by_id.get(to_move["crew_id"])
                            if crew_obj:
                                current_load = sum(
                                    sum(jobs_by_id[j].estimated_minutes for j in e2["job_ids"] if j in jobs_by_id)
                                    for e2 in draft
                                    if e2["crew_id"] == to_move["crew_id"] and e2["day"] == alt_day
                                )
                                move_load = sum(j.estimated_minutes for j in jobs_in_entry)
                                if current_load + move_load + 35 > crew_obj.daily_minutes:
                                    continue
                            to_move["day"] = alt_day
                            # Update per_day_equipment cache
                            per_day_equipment[day][kind].remove(to_move["crew_id"])
                            per_day_equipment.setdefault(alt_day, {}).setdefault(kind, []).append(to_move["crew_id"])
                            moved = True
                            resolved_conflicts.append(
                                f"Moved {to_move['crew_id']} {kind.value} jobs from {day.isoformat()} to {alt_day.isoformat()} to resolve equipment contention."
                            )
                            await ctx.emit(
                                self.name,
                                "resolve",
                                f"Resolved {kind.value} conflict on {day.isoformat()}: moved {to_move['crew_id']} to {alt_day.isoformat()}.",
                            )
                            break
                    if not moved:
                        # Could not auto-resolve — keep in conflicts list
                        pass
                    else:
                        # Remove the resolved conflict string that was already added
                        if conflicts:
                            conflicts = [
                                c for c in conflicts
                                if not (day.isoformat() in c and kind.value in c)
                            ]

        ctx.blackboard["equipment_conflicts"] = conflicts
        ctx.blackboard["equipment_gaps"] = gaps
        await ctx.emit(
            self.name,
            "done",
            f"Equipment check: {len(conflicts)} day-level conflicts, {len(gaps)} per-job gaps.",
        )

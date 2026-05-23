"""EquipmentAgent - validates equipment availability for each crew/day.

Anthropic pattern: **Parallelization (sectioning)**.

The supervisor runs this agent concurrently with TimeBudgetAgent because
they validate independent aspects of the same draft plan. Sectioning is
more reliable than asking one prompt to do both.

Each crew has a fixed equipment loadout. The agent flags any job that
requires equipment the assigned crew does not carry, and surfaces a clear
remediation (swap crews, reschedule day, or rent).

Equipment exclusivity: single-unit equipment (e.g. scissor_lift, where
the company owns exactly one unit) can only be used by one job per day
across the entire schedule. Any second job requiring the same single-unit
equipment on the same day is deferred — the lower-revenue job is bumped
to its next available date before the schedule is written.
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

        # Track which jobs must be moved to unscheduled due to equipment conflicts.
        conflict_deferred: list[str] = []

        # ── Phase 1: Per-day per-job exclusivity lock ─────────────────────────
        # For each equipment kind, compute total company-wide quantity.
        # If the quantity is 1 (single-unit equipment like scissor_lift), at most
        # one job per day across the ENTIRE schedule may require it.
        # Lower-revenue jobs are bumped before the schedule is written.
        total_qty_by_kind: dict[EquipmentKind, int] = {}
        for eq in store.list_equipment():
            total_qty_by_kind[eq.kind] = total_qty_by_kind.get(eq.kind, 0) + eq.quantity

        # Equipment kinds that require a full-day exclusive commitment — even
        # sequential jobs on the same crew cannot share these in one shift because
        # of the setup/teardown/permit overhead involved.  Currently: scissor_lift.
        _EXCLUSIVE_KINDS: frozenset[EquipmentKind] = frozenset({EquipmentKind.SCISSOR_LIFT})

        # Build per-day per-kind job list from job requirements (not crew loadouts)
        per_day_job_equip: dict[tuple[date, EquipmentKind], list[tuple[str, str, float]]] = defaultdict(list)
        for entry in draft:
            for jid in entry["job_ids"]:
                job = jobs_by_id.get(jid)
                if not job:
                    continue
                for kind in job.required_equipment:
                    if kind in _EXCLUSIVE_KINDS:
                        per_day_job_equip[(entry["day"], kind)].append(
                            (jid, entry["crew_id"], job.price)
                        )

        for (day, kind), job_entries in per_day_job_equip.items():
            total = total_qty_by_kind.get(kind, 1)
            if len(job_entries) <= total:
                continue
            # More jobs than units — bump lower-revenue jobs
            job_entries.sort(key=lambda x: -x[2])
            excess = job_entries[total:]
            conflict_msg = (
                f"On {day.isoformat()}, {len(job_entries)} job(s) require "
                f"{kind.value} but only {total} unit(s) exist. "
                f"Lower-revenue job(s) bumped: {[jid for jid, _, _ in excess]}."
            )
            conflicts.append(conflict_msg)
            await ctx.emit(
                self.name,
                "exclusivity_conflict",
                f"Equipment exclusivity: {kind.value} on {day.isoformat()} — "
                f"{len(job_entries)} jobs, {total} unit(s). Bumping lower-revenue jobs.",
            )
            for jid, crew_id, price in excess:
                if jid not in conflict_deferred:
                    conflict_deferred.append(jid)
                    await ctx.emit(
                        self.name,
                        "defer",
                        f"Job {jid} (${price:.0f}) bumped: {kind.value} exclusivity "
                        f"conflict on {day.isoformat()} (crew {crew_id}).",
                    )
                    # Remove the bumped job from its draft entry
                    for entry in draft:
                        if entry["day"] == day and jid in entry["job_ids"]:
                            entry["job_ids"] = [j for j in entry["job_ids"] if j != jid]

        # ── Phase 2: Cross-crew equipment contention (multi-crew, same day) ───
        # Guards against two different crews both needing the same scarce equipment.
        per_day_crew_equip: dict[date, dict[EquipmentKind, list[str]]] = defaultdict(lambda: defaultdict(list))
        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            for eid in crew.equipment_ids:
                e = store.get_equipment(eid)
                if e:
                    per_day_crew_equip[entry["day"]][e.kind].append(crew.id)

        for day, kinds in per_day_crew_equip.items():
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
                        conflicting_entries = [
                            e for e in draft
                            if e["day"] == day
                            and any(
                                store.get_equipment(eid) and store.get_equipment(eid).kind == kind
                                for eid in crews_by_id[e["crew_id"]].equipment_ids
                            )
                        ]
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

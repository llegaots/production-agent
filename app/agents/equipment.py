"""EquipmentAgent - validates equipment availability for each crew/day.

Anthropic pattern: **Parallelization (sectioning)**.

The supervisor runs this agent concurrently with TimeBudgetAgent because
they validate independent aspects of the same draft plan. Sectioning is
more reliable than asking one prompt to do both.

Each crew has a fixed equipment loadout. The agent flags any job that
requires equipment the assigned crew does not carry, and surfaces a clear
remediation (swap crews, reschedule day, or rent).  When a day-level
equipment conflict is detected (two crews need the same scarce piece of
kit on the same day) the agent attempts to resolve it by moving the
lower-priority conflicting job to another available day before falling back
to a conflict warning.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..models import EquipmentKind
from ..storage import store
from .base import Agent, AgentContext, week_days


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
        days = week_days(ctx.week_start)

        # ── Day-level contention check (same equipment kind, multiple crews) ──
        # Build a per-day map: kind → list of (entry_index, crew_id)
        def _build_per_day() -> dict[date, dict[EquipmentKind, list[tuple[int, str]]]]:
            pd: dict[date, dict[EquipmentKind, list[tuple[int, str]]]] = defaultdict(lambda: defaultdict(list))
            for idx, entry in enumerate(draft):
                crew = crews_by_id[entry["crew_id"]]
                for eid in crew.equipment_ids:
                    e = store.get_equipment(eid)
                    if e:
                        pd[entry["day"]][e.kind].append((idx, crew.id))
            return pd

        per_day_equipment = _build_per_day()
        resolved_moves: list[str] = []

        for day, kinds in list(per_day_equipment.items()):
            for kind, idx_crew_pairs in list(kinds.items()):
                if len(idx_crew_pairs) <= 1:
                    continue
                crew_ids_on_day = [cid for _, cid in idx_crew_pairs]
                total = sum(eq.quantity for eq in store.list_equipment() if eq.kind == kind)
                if len(crew_ids_on_day) <= total:
                    continue

                # Conflict: more crews need this kind than units exist.
                # Attempt to resolve by moving the lowest-priority crew's
                # jobs to a different available day.
                await ctx.emit(
                    self.name,
                    "conflict",
                    f"Equipment contention on {day.isoformat()} for {kind.value} "
                    f"({len(crew_ids_on_day)} crews need it, only {total} unit(s)).",
                )

                # Sort: keep the first entry (highest-priority / heaviest load),
                # try to move subsequent ones.
                sorted_pairs = sorted(
                    idx_crew_pairs,
                    key=lambda ic: -sum(
                        jobs_by_id[jid].estimated_minutes
                        for jid in draft[ic[0]]["job_ids"]
                        if jid in jobs_by_id
                    ),
                )
                move_pairs = sorted_pairs[total:]   # extras beyond available units

                moved = False
                for entry_idx, crew_id in move_pairs:
                    entry = draft[entry_idx]
                    entry_jobs = [jobs_by_id[jid] for jid in entry["job_ids"] if jid in jobs_by_id]
                    total_mins = sum(j.estimated_minutes for j in entry_jobs)

                    # Find another day in the week where:
                    # (a) the conflicting kind is not overloaded,
                    # (b) all jobs fit within their date windows,
                    # (c) crew has headroom.
                    crew_obj = crews_by_id[crew_id]
                    used_by_crew: dict[date, int] = {}
                    for e2 in draft:
                        if e2["crew_id"] == crew_id:
                            used_by_crew[e2["day"]] = used_by_crew.get(e2["day"], 0) + sum(
                                jobs_by_id[jid].estimated_minutes
                                for jid in e2["job_ids"] if jid in jobs_by_id
                            )

                    alt_day: date | None = None
                    for candidate in days:
                        if candidate == day:
                            continue
                        # Check date windows for all jobs in this entry
                        if any(
                            candidate < j.earliest_date or candidate > j.latest_date
                            for j in entry_jobs
                        ):
                            continue
                        # Check capacity headroom
                        drive_budget = 20 + 15 * max(0, len(entry_jobs) - 1)
                        if used_by_crew.get(candidate, 0) + total_mins + drive_budget > crew_obj.daily_minutes:
                            continue
                        # Check equipment contention on candidate day (rebuild per-day for this kind)
                        cand_crews_with_kind = [
                            cid2
                            for e2 in draft
                            if e2["day"] == candidate
                            for eid2 in crews_by_id[e2["crew_id"]].equipment_ids
                            if store.get_equipment(eid2) and store.get_equipment(eid2).kind == kind  # type: ignore[union-attr]
                            for cid2 in [e2["crew_id"]]
                        ]
                        # Count unique crew IDs
                        cand_unique = list(dict.fromkeys(cand_crews_with_kind))
                        if len(cand_unique) + 1 > total:
                            continue
                        alt_day = candidate
                        break

                    if alt_day is not None:
                        old_day = entry["day"]
                        draft[entry_idx]["day"] = alt_day
                        msg = (
                            f"Resolved equipment conflict: moved {crew_id} jobs "
                            f"{entry['job_ids']} from {old_day.isoformat()} "
                            f"to {alt_day.isoformat()} ({kind.value} contention)."
                        )
                        resolved_moves.append(msg)
                        moved = True
                        await ctx.emit(self.name, "resolve", msg)
                    else:
                        conflicts.append(
                            f"On {day.isoformat()}, {len(crew_ids_on_day)} crews need "
                            f"{kind.value} but only {total} unit(s) exist — "
                            f"could not auto-resolve (no alternative day fits)."
                        )

        # per-job equipment fit
        for entry in draft:
            crew = crews_by_id[entry["crew_id"]]
            available = crew_kinds[crew.id]
            for job_id in entry["job_ids"]:
                job = jobs_by_id.get(job_id)
                if not job:
                    continue
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
                        f"Job {job_id} on {crew.name}/{entry['day'].isoformat()} is missing: "
                        f"{', '.join(m.value for m in missing)}.",
                    )

        ctx.blackboard["equipment_conflicts"] = conflicts
        ctx.blackboard["equipment_gaps"] = gaps
        # Expose resolved moves so the supervisor summary can mention them.
        ctx.blackboard["equipment_resolved_moves"] = resolved_moves
        await ctx.emit(
            self.name,
            "done",
            f"Equipment check: {len(conflicts)} day-level conflict(s) remaining, "
            f"{len(gaps)} per-job gap(s). {len(resolved_moves)} conflict(s) auto-resolved.",
        )

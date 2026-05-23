"""Compare a replayed orchestrator run to a golden schedule snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.orchestrator.schemas import ScheduleRunResult
from evals.metrics import collect_trial_metrics


@dataclass(frozen=True)
class ScheduleAssignments:
    """job_id → crew_id and calendar day (ISO date string)."""

    by_job: dict[str, dict[str, str | None]]

    @classmethod
    def from_schedule_row(cls, row: dict[str, Any]) -> ScheduleAssignments:
        raw = row.get("assignments") or {}
        by_job: dict[str, dict[str, str | None]] = {}
        if isinstance(raw, dict):
            for jid, val in raw.items():
                if isinstance(val, dict):
                    by_job[jid] = {
                        "crew_id": val.get("crew_id"),
                        "day": val.get("day"),
                    }
        return cls(by_job=by_job)

    @classmethod
    def from_optimizer_result(
        cls,
        optimizer_result: dict[str, Any],
        *,
        target_date: date,
    ) -> ScheduleAssignments:
        day_str = target_date.isoformat()
        by_job: dict[str, dict[str, str | None]] = {}
        for route in optimizer_result.get("routes") or []:
            crew_id = route.get("crew_id")
            for stop in route.get("stops") or []:
                jid = stop.get("job_id")
                if jid:
                    by_job[jid] = {"crew_id": crew_id, "day": day_str}
        return cls(by_job=by_job)

    def assigned_job_ids(self) -> set[str]:
        return {jid for jid, a in self.by_job.items() if a.get("crew_id")}


@dataclass(frozen=True)
class GoldenDriftMetrics:
    schedule_id: str
    golden_job_count: int
    golden_assigned_count: int
    replay_assigned_count: int
    same_crew_pct: float
    same_day_pct: float
    drive_minutes_delta: int
    preference_violations_delta: int
    golden_drive_minutes: int
    replay_drive_minutes: int
    golden_preference_violations: int
    replay_preference_violations: int
    replay_status: str
    replay_approved: bool
    replay_iteration_count: int
    crew_mismatches: list[dict[str, str]]
    day_mismatches: list[dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "golden_job_count": self.golden_job_count,
            "golden_assigned_count": self.golden_assigned_count,
            "replay_assigned_count": self.replay_assigned_count,
            "same_crew_pct": self.same_crew_pct,
            "same_day_pct": self.same_day_pct,
            "drive_minutes_delta": self.drive_minutes_delta,
            "preference_violations_delta": self.preference_violations_delta,
            "golden_drive_minutes": self.golden_drive_minutes,
            "replay_drive_minutes": self.replay_drive_minutes,
            "golden_preference_violations": self.golden_preference_violations,
            "replay_preference_violations": self.replay_preference_violations,
            "replay_status": self.replay_status,
            "replay_approved": self.replay_approved,
            "replay_iteration_count": self.replay_iteration_count,
            "crew_mismatches": self.crew_mismatches,
            "day_mismatches": self.day_mismatches,
        }


def compare_to_golden(
    golden_row: dict[str, Any],
    replay_result: ScheduleRunResult,
    *,
    replay_assignments: ScheduleAssignments,
    replay_metrics: Any,
) -> GoldenDriftMetrics:
    golden_assign = ScheduleAssignments.from_schedule_row(golden_row)
    golden_assigned = golden_assign.assigned_job_ids()
    replay_assigned = replay_assignments.assigned_job_ids()

    crew_match = 0
    day_match = 0
    crew_mismatches: list[dict[str, str]] = []
    day_mismatches: list[dict[str, str]] = []

    for jid in golden_assigned:
        g = golden_assign.by_job.get(jid, {})
        r = replay_assignments.by_job.get(jid, {})
        g_crew = g.get("crew_id")
        r_crew = r.get("crew_id")
        g_day = g.get("day")
        r_day = r.get("day")

        if g_crew and r_crew and g_crew == r_crew:
            crew_match += 1
        elif g_crew:
            crew_mismatches.append(
                {"job_id": jid, "golden_crew": g_crew or "", "replay_crew": r_crew or "(unassigned)"}
            )

        if g_day and r_day and g_day == r_day:
            day_match += 1
        elif g_day:
            day_mismatches.append(
                {"job_id": jid, "golden_day": g_day or "", "replay_day": r_day or "(none)"}
            )

    n = len(golden_assigned) or 1
    same_crew_pct = 100.0 * crew_match / n
    same_day_pct = 100.0 * day_match / n

    golden_drive = int(golden_row.get("total_drive_minutes") or 0)
    golden_pref = int(golden_row.get("preference_violations") or 0)
    replay_drive = replay_metrics.total_drive_minutes
    replay_pref = replay_metrics.preference_violations

    return GoldenDriftMetrics(
        schedule_id=str(golden_row["id"]),
        golden_job_count=len(golden_row.get("job_ids") or []),
        golden_assigned_count=len(golden_assigned),
        replay_assigned_count=len(replay_assigned),
        same_crew_pct=same_crew_pct,
        same_day_pct=same_day_pct,
        drive_minutes_delta=replay_drive - golden_drive,
        preference_violations_delta=replay_pref - golden_pref,
        golden_drive_minutes=golden_drive,
        replay_drive_minutes=replay_drive,
        golden_preference_violations=golden_pref,
        replay_preference_violations=replay_pref,
        replay_status=replay_result.status,
        replay_approved=bool(replay_result.approved),
        replay_iteration_count=replay_result.iteration_count,
        crew_mismatches=crew_mismatches[:20],
        day_mismatches=day_mismatches[:20],
    )

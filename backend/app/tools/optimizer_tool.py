from __future__ import annotations

from datetime import date

from app.optimizer import solve
from app.optimizer.models import (
    OptimizerInput,
    ScheduleCrew,
    ScheduleJob,
    TimeWindow,
    TravelMatrix,
)
from app.tools.crew_availability import get_crew_availability
from app.tools.schemas import GetCrewAvailabilityInput, GetTravelMatrixInput, RunOptimizerInput, RunOptimizerOutput
from app.tools.travel_matrix import get_travel_matrix
from app.tools._db import tools_db


def _job_time_window(job: dict, target: date) -> TimeWindow:
    """Map job date range to minute window on target day (simplified)."""
    notes = job.get("notes") or ""
    if "tw_start:" in notes and "tw_end:" in notes:
        try:
            part = notes.split("tw_start:")[1]
            start_s, rest = part.split("tw_end:", 1)
            return TimeWindow(
                earliest_minute=int(start_s.strip().split()[0]),
                latest_minute=int(rest.strip().split()[0]),
            )
        except (ValueError, IndexError):
            pass
    return TimeWindow(earliest_minute=60, latest_minute=420)


def _preferred_crew_id(job: dict) -> str | None:
    notes = job.get("notes") or ""
    if "preferred_crew:" in notes:
        return notes.split("preferred_crew:")[1].split()[0].strip()
    return None


def _load_crew_equipment(crew_ids: list[str]) -> dict[str, list[str]]:
    db = tools_db()
    links = (
        db.table("crew_equipment")
        .select("crew_id, equipment_id")
        .in_("crew_id", crew_ids)
        .execute()
        .data
        or []
    )
    eq_ids = list({l["equipment_id"] for l in links})
    kinds: dict[str, str] = {}
    if eq_ids:
        for row in db.table("equipment").select("id, kind").in_("id", eq_ids).execute().data or []:
            kinds[row["id"]] = row["kind"]
    out: dict[str, list[str]] = {cid: [] for cid in crew_ids}
    for link in links:
        k = kinds.get(link["equipment_id"])
        if k:
            out[link["crew_id"]].append(k)
    return out


def run_optimizer(inp: RunOptimizerInput) -> RunOptimizerOutput:
    """Build optimizer input from Supabase, run OR-Tools, return structured result."""
    db = tools_db()
    jobs = (
        db.table("jobs")
        .select(
            "id, lat, lng, estimated_minutes, required_skills, required_equipment, "
            "earliest_date, latest_date, status, notes"
        )
        .in_("id", inp.job_ids)
        .execute()
        .data
        or []
    )
    if len(jobs) != len(inp.job_ids):
        raise ValueError("One or more jobs not found")

    avail = get_crew_availability(
        GetCrewAvailabilityInput(target_date=inp.target_date, crew_ids=inp.crew_ids)
    )
    crew_ids = inp.crew_ids or [c.crew_id for c in avail.crews if c.is_available]
    if not crew_ids:
        raise ValueError("No available crews for target date")

    travel_out = get_travel_matrix(
        GetTravelMatrixInput(
            job_ids=inp.job_ids,
            crew_ids=crew_ids,
            force_refresh=inp.force_refresh_travel,
        )
    )

    node_by_ref = {n.ref_id: n.node_index for n in travel_out.nodes}
    crew_equip = _load_crew_equipment(crew_ids)
    avail_by_id = {c.crew_id: c for c in avail.crews}

    opt_crews: list[ScheduleCrew] = []
    for cid in crew_ids:
        row = avail_by_id[cid]
        if cid not in node_by_ref:
            raise ValueError(f"Crew {cid} missing from travel nodes")
        opt_crews.append(
            ScheduleCrew(
                id=cid,
                depot_index=node_by_ref[cid],
                skills=row.skills,
                equipment_kinds=crew_equip.get(cid, []),
                shift_start_minute=row.shift_start_minute,
                shift_end_minute=row.shift_end_minute,
            )
        )

    opt_jobs: list[ScheduleJob] = []
    for job in jobs:
        if job["id"] not in node_by_ref:
            raise ValueError(f"Job {job['id']} missing from travel nodes")
        opt_jobs.append(
            ScheduleJob(
                id=job["id"],
                node_index=node_by_ref[job["id"]],
                service_minutes=int(job["estimated_minutes"]),
                time_window=_job_time_window(job, inp.target_date),
                required_skills=list(job.get("required_skills") or []),
                required_equipment=list(job.get("required_equipment") or []),
                preferred_crew_id=_preferred_crew_id(job),
            )
        )

    optimizer_input = OptimizerInput(
        crews=opt_crews,
        jobs=opt_jobs,
        travel=TravelMatrix(minutes=travel_out.minutes),
        horizon_minutes=inp.horizon_minutes,
        time_limit_seconds=inp.time_limit_seconds,
    )
    result = solve(optimizer_input)

    return RunOptimizerOutput(
        target_date=inp.target_date,
        travel=travel_out,
        optimizer_input=optimizer_input,
        result=result,
    )

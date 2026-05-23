"""Optimizer lab: CRUD jobs + run OR-Tools only (no orchestrator)."""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.optimizer_lab.schemas import (
    OptimizerLabJobUpdate,
    OptimizerLabRunRequest,
    OptimizerLabRunResponse,
)
from app.repositories.operations import OperationsRepository
from app.tools import check_equipment, get_crew_availability, run_optimizer
from app.tools.schemas import (
    CheckEquipmentInput,
    GetCrewAvailabilityInput,
    RunOptimizerInput,
)

router = APIRouter(prefix="/optimizer-lab", tags=["optimizer-lab"])


@router.get("/jobs")
def list_jobs(
    id_prefix: str = Query("qa_job_", description="Filter job ids starting with this prefix"),
    id_from: str | None = Query(None, description="Minimum job id (inclusive string sort)"),
    id_to: str | None = Query(None, description="Maximum job id (inclusive string sort)"),
    target_date: date | None = Query(
        None,
        description="Only jobs whose date window includes this day",
    ),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return OperationsRepository().list_jobs_for_lab(
        id_prefix=id_prefix,
        id_from=id_from,
        id_to=id_to,
        target_date=target_date,
        status=status,
        limit=limit,
    )


@router.patch("/jobs/{job_id}")
def update_job(job_id: str, body: OptimizerLabJobUpdate) -> dict[str, Any]:
    try:
        return OperationsRepository().update_job(
            job_id,
            body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, str]:
    try:
        OperationsRepository().delete_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": job_id}


@router.get("/crews")
def list_crews_for_lab(target_date: date) -> list[dict[str, Any]]:
    avail = get_crew_availability(
        GetCrewAvailabilityInput(target_date=target_date, crew_ids=None),
    )
    repo = OperationsRepository()
    names = {c.id: c.name for c in repo.list_crews()}
    out: list[dict[str, Any]] = []
    for c in avail.crews:
        out.append(
            {
                "crew_id": c.crew_id,
                "name": names.get(c.crew_id, c.crew_id),
                "is_available": c.is_available,
                "skills": c.skills,
                "shift_start_minute": c.shift_start_minute,
                "shift_end_minute": c.shift_end_minute,
            }
        )
    return out


@router.post("/run", response_model=OptimizerLabRunResponse)
def run_optimizer_lab(body: OptimizerLabRunRequest) -> OptimizerLabRunResponse:
    settings = get_settings()
    avail = get_crew_availability(
        GetCrewAvailabilityInput(target_date=body.target_date, crew_ids=body.crew_ids),
    )
    crew_ids = body.crew_ids or [c.crew_id for c in avail.crews if c.is_available]
    if not crew_ids:
        raise HTTPException(status_code=400, detail="No available crews for target date")

    equip = check_equipment(
        CheckEquipmentInput(job_ids=body.job_ids, crew_ids=crew_ids),
    )

    t0 = time.perf_counter()
    try:
        opt = run_optimizer(
            RunOptimizerInput(
                target_date=body.target_date,
                job_ids=body.job_ids,
                crew_ids=crew_ids,
                time_limit_seconds=body.time_limit_seconds or settings.optimizer_time_limit_seconds,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    elapsed = time.perf_counter() - t0

    result = opt.result
    routes = [r.model_dump(mode="json") for r in result.routes if r.stops]

    return OptimizerLabRunResponse(
        target_date=body.target_date.isoformat(),
        status=result.status,
        assigned_count=len(result.assigned_job_ids),
        unassigned_count=len(result.unassigned_job_ids),
        assigned_job_ids=list(result.assigned_job_ids),
        unassigned_job_ids=list(result.unassigned_job_ids),
        routes=routes,
        messages=list(result.messages),
        equipment_check=equip.model_dump(mode="json"),
        duration_seconds=round(elapsed, 2),
    )

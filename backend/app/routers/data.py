from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.repositories.operations import OperationsRepository

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/summary")
def data_summary() -> dict:
    """Row counts for core Phase 2 tables."""
    try:
        return OperationsRepository().count_summary()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/clients")
def list_clients(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    repo = OperationsRepository()
    return [c.model_dump() for c in repo.list_clients(limit=limit)]


@router.get("/crews")
def list_crews() -> list[dict]:
    repo = OperationsRepository()
    return [c.model_dump() for c in repo.list_crews()]


@router.get("/jobs/pending")
def list_pending_jobs(
    limit: int = Query(50, ge=1, le=200),
    on_or_after: date | None = None,
) -> list[dict]:
    repo = OperationsRepository()
    return [j.model_dump() for j in repo.list_pending_jobs(on_or_after=on_or_after, limit=limit)]

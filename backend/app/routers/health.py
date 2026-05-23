from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.db.postgres import check_postgres_connection
from app.db.supabase_client import check_supabase_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/postgres")
def health_postgres() -> dict:
    """Test direct Postgres connection (SUPABASE_DB_URL)."""
    settings = get_settings()
    try:
        return check_postgres_connection(settings)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "error": str(exc), "hint": "Check SUPABASE_DB_URL in .env"},
        ) from exc


@router.get("/health/supabase")
def health_supabase() -> dict:
    """Test Supabase REST API + supabase-py client (SUPABASE_URL + SERVICE_KEY)."""
    settings = get_settings()
    try:
        return check_supabase_connection(settings)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "error": str(exc),
                "hint": "Check SUPABASE_URL and SUPABASE_SERVICE_KEY in .env",
            },
        ) from exc


@router.get("/health/all")
def health_all() -> dict:
    """Run both connection checks in one request."""
    settings = get_settings()
    result: dict = {"status": "ok", "postgres": None, "supabase": None}
    errors: list[str] = []

    try:
        result["postgres"] = check_postgres_connection(settings)
    except Exception as exc:
        result["postgres"] = {"ok": False, "error": str(exc)}
        errors.append("postgres")

    try:
        result["supabase"] = check_supabase_connection(settings)
    except Exception as exc:
        result["supabase"] = {"ok": False, "error": str(exc)}
        errors.append("supabase")

    if errors:
        result["status"] = "degraded"
        raise HTTPException(status_code=503, detail=result)

    return result

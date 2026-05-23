"""Data access via supabase-py (service role — server-side only)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.db.supabase_client import get_supabase_client
from app.models.schemas import Client, Crew, CrewSkill, Equipment, Job, ServiceHistoryRecord


class OperationsRepository:
    def __init__(self) -> None:
        self._db = get_supabase_client()

    def count_summary(self) -> dict[str, int]:
        tables = (
            "clients",
            "crews",
            "equipment",
            "crew_skills",
            "jobs",
            "service_history",
        )
        out: dict[str, int] = {}
        for table in tables:
            resp = self._db.table(table).select("*", count="exact").limit(0).execute()
            out[table] = resp.count or 0
        return out

    def list_clients(self, limit: int = 20) -> list[Client]:
        rows = (
            self._db.table("clients")
            .select("*")
            .order("name")
            .limit(limit)
            .execute()
            .data
            or []
        )
        return [Client.model_validate(r) for r in rows]

    def list_crews(self) -> list[Crew]:
        rows = self._db.table("crews").select("*").order("name").execute().data or []
        return [Crew.model_validate(r) for r in rows]

    def list_crew_skills(self, crew_id: str | None = None) -> list[CrewSkill]:
        q = self._db.table("crew_skills").select("*")
        if crew_id:
            q = q.eq("crew_id", crew_id)
        rows = q.execute().data or []
        return [CrewSkill.model_validate(r) for r in rows]

    def list_equipment(self) -> list[Equipment]:
        rows = self._db.table("equipment").select("*").order("kind").execute().data or []
        return [Equipment.model_validate(r) for r in rows]

    def list_pending_jobs(
        self,
        *,
        on_or_after: date | None = None,
        limit: int = 50,
    ) -> list[Job]:
        q = self._db.table("jobs").select("*").eq("status", "pending")
        if on_or_after:
            q = q.gte("earliest_date", on_or_after.isoformat())
        rows = q.order("earliest_date").limit(limit).execute().data or []
        return [Job.model_validate(r) for r in rows]

    def list_service_history(self, client_id: str, limit: int = 10) -> list[ServiceHistoryRecord]:
        rows = (
            self._db.table("service_history")
            .select("*")
            .eq("client_id", client_id)
            .order("completed_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        return [ServiceHistoryRecord.model_validate(r) for r in rows]

    def list_customers_view(self, limit: int = 5) -> list[dict[str, Any]]:
        """Query the `customers` view (alias over clients)."""
        return (
            self._db.table("customers")
            .select("*")
            .order("name")
            .limit(limit)
            .execute()
            .data
            or []
        )

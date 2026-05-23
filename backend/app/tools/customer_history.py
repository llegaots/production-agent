from __future__ import annotations

from app.tools._db import tools_db
from app.tools.schemas import (
    GetCustomerHistoryInput,
    GetCustomerHistoryOutput,
    ServiceHistoryItem,
)


def get_customer_history(inp: GetCustomerHistoryInput) -> GetCustomerHistoryOutput:
    """Service history for a client (customers table = clients)."""
    db = tools_db()
    client = (
        db.table("clients").select("id, name").eq("id", inp.client_id).limit(1).execute().data
    )
    if not client:
        raise ValueError(f"Client not found: {inp.client_id}")

    rows = (
        db.table("service_history")
        .select("*")
        .eq("client_id", inp.client_id)
        .order("completed_at", desc=True)
        .limit(inp.limit)
        .execute()
        .data
        or []
    )

    history = [ServiceHistoryItem.model_validate(r) for r in rows]
    return GetCustomerHistoryOutput(
        client_id=inp.client_id,
        client_name=client[0]["name"],
        history=history,
        total_visits=len(history),
    )

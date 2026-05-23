from __future__ import annotations

from app.tools._db import tools_db
from app.tools.schemas import (
    CriticFeedbackItem,
    GetPreviousCriticFeedbackInput,
    GetPreviousCriticFeedbackOutput,
)


def get_previous_critic_feedback(
    inp: GetPreviousCriticFeedbackInput,
) -> GetPreviousCriticFeedbackOutput:
    """Latest critic / plan-reviewer notes for an attempt or plan."""
    if not inp.schedule_attempt_id and not inp.plan_id:
        raise ValueError("Provide schedule_attempt_id or plan_id")

    items: list[CriticFeedbackItem] = []
    db = tools_db()

    fq = db.table("critic_feedback").select("*").order("created_at", desc=True).limit(inp.limit)
    if inp.schedule_attempt_id:
        fq = fq.eq("schedule_attempt_id", str(inp.schedule_attempt_id))
    if inp.plan_id:
        fq = fq.eq("plan_id", str(inp.plan_id))
    for row in fq.execute().data or []:
        items.append(
            CriticFeedbackItem(
                id=row["id"],
                source="critic_feedback",
                score=row.get("score"),
                passed=row.get("passed"),
                concerns=list(row.get("concerns") or []),
                narrative=row.get("narrative") or "",
                created_at=row.get("created_at"),
            )
        )

    if inp.plan_id:
        pr = (
            db.table("plan_reviews")
            .select("*")
            .eq("plan_id", str(inp.plan_id))
            .limit(1)
            .execute()
            .data
        )
        if pr:
            row = pr[0]
            items.append(
                CriticFeedbackItem(
                    source="plan_review",
                    score=100 - int(row.get("risk_score") or 0),
                    passed=int(row.get("risk_score") or 100) < 50,
                    concerns=[row["top_concern"]] if row.get("top_concern") else [],
                    narrative=row.get("narrative") or "",
                    recommendation=row.get("recommendation"),
                    top_concern=row.get("top_concern"),
                    created_at=row.get("created_at"),
                )
            )

    items.sort(key=lambda x: x.created_at or "", reverse=True)
    return GetPreviousCriticFeedbackOutput(items=items[: inp.limit])

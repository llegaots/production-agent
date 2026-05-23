from __future__ import annotations

from datetime import datetime, timezone

from app.tools._db import tools_db
from app.tools.schemas import SaveScheduleAttemptInput, SaveScheduleAttemptOutput


def save_schedule_attempt(inp: SaveScheduleAttemptInput) -> SaveScheduleAttemptOutput:
    """Persist an optimizer run for audit and critic replay."""
    row = {
        "target_date": inp.target_date.isoformat(),
        "job_ids": inp.job_ids,
        "crew_ids": inp.crew_ids,
        "optimizer_input": inp.optimizer_input.model_dump(mode="json") if inp.optimizer_input else None,
        "optimizer_result": inp.result.model_dump(mode="json"),
        "status": inp.result.status,
        "messages": inp.messages or inp.result.messages,
    }
    resp = tools_db().table("schedule_attempts").insert(row).execute()
    if not resp.data:
        raise RuntimeError("Failed to save schedule_attempt")
    saved = resp.data[0]
    return SaveScheduleAttemptOutput(
        attempt_id=saved["id"],
        created_at=datetime.fromisoformat(saved["created_at"].replace("Z", "+00:00")),
    )

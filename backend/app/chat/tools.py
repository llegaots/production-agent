"""Chat-agent tools (scheduling orchestrator)."""

from __future__ import annotations

from typing import Any

from app.chat.preview import build_schedule_preview
from app.config import get_settings
from app.orchestrator import run_scheduling_mission
from app.orchestrator.schemas import ScheduleWeekInput

SCHEDULING_TOOL_DEFINITION: dict[str, Any] = {
    "name": "run_scheduling_orchestrator",
    "description": (
        "Run the scheduling pipeline (constraints, optimizer, critic). "
        "Call when the dispatcher asks to schedule jobs for a week."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "user_request": {
                "type": "string",
                "description": "Scheduling goal in natural language",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Critic iteration cap (default 1 in chat)",
            },
        },
        "required": ["user_request"],
    },
}


def execute_scheduling_tool(
    tool_input: dict[str, Any],
    *,
    use_orchestrator_agent: bool | None = None,
) -> dict[str, Any]:
    """
    Chat always uses fast single-day preview (no multi-day agent loop).
    Full week orchestration is available via CLI / evals.
    """
    settings = get_settings()
    # Never run the Anthropic tool-use agent loop from chat — it blocks SSE for minutes.
    use_agent = False if use_orchestrator_agent is None else bool(use_orchestrator_agent)

    result = run_scheduling_mission(
        ScheduleWeekInput(
            user_request=str(tool_input.get("user_request", "Schedule pending jobs")),
            max_iterations=int(tool_input.get("max_iterations") or 1),
            use_llm_critic=False,
            use_agent=use_agent and bool(settings.anthropic_api_key),
            job_load_limit=12,
            single_day_preview=True,
        )
    )
    preview = build_schedule_preview(result)
    assigned = len(preview.assigned_job_ids)
    total = assigned + len(preview.unassigned_job_ids)
    summary = (
        f"{assigned} jobs assigned"
        + (f" ({len(preview.unassigned_job_ids)} deferred)" if preview.unassigned_job_ids else "")
        + f". Status: {result.status}."
    )
    return {
        "schedule_run_id": str(result.schedule_run_id),
        "status": result.status,
        "approved": result.approved,
        "summary": summary,
        "assigned_count": assigned,
        "total_jobs": total or assigned,
        "schedule_preview": preview.model_dump(mode="json"),
    }


def wants_scheduling(text: str) -> bool:
    lower = text.lower()
    hints = (
        "schedule",
        "next week",
        "my week",
        "this week",
        "plan the week",
        "assign crews",
        "routing",
    )
    return any(h in lower for h in hints)

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
        "Run the full weekly scheduling pipeline (constraints, optimizer, critic). "
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
                "description": "Critic iteration cap (default 4)",
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
    settings = get_settings()
    use_agent = use_orchestrator_agent
    if use_agent is None:
        use_agent = bool(settings.anthropic_api_key)

    result = run_scheduling_mission(
        ScheduleWeekInput(
            user_request=str(tool_input.get("user_request", "Schedule pending jobs")),
            max_iterations=int(tool_input.get("max_iterations") or settings.orchestrator_max_iterations),
            use_llm_critic=False,
            use_agent=use_agent and bool(settings.anthropic_api_key),
        )
    )
    preview = build_schedule_preview(result)
    return {
        "schedule_run_id": str(result.schedule_run_id),
        "status": result.status,
        "approved": result.approved,
        "summary": result.summary,
        "schedule_preview": preview.model_dump(mode="json"),
    }


def wants_scheduling(text: str) -> bool:
    lower = text.lower()
    hints = ("schedule", "next week", "plan the week", "assign crews", "routing")
    return any(h in lower for h in hints)

"""Anthropic tool schemas and execution dispatch."""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from app.critic.review import review_schedule
from app.critic.schemas import ReviewScheduleInput
from app.orchestrator.context import OrchestratorContext
from app.tools import (
    check_equipment,
    get_crew_availability,
    get_customer_history,
    get_previous_critic_feedback,
    get_travel_matrix,
    get_weather,
    run_optimizer,
    save_schedule_attempt,
)
from app.tools.schemas import (
    CheckEquipmentInput,
    GetCrewAvailabilityInput,
    GetCustomerHistoryInput,
    GetPreviousCriticFeedbackInput,
    GetTravelMatrixInput,
    GetWeatherInput,
    RunOptimizerInput,
    SaveScheduleAttemptInput,
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_crew_availability",
        "description": "Crew shift availability for a date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "crew_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["target_date"],
        },
    },
    {
        "name": "get_weather",
        "description": "Weather forecast for exterior work at a lat/lng on a date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "forecast_date": {"type": "string"},
            },
            "required": ["lat", "lng", "forecast_date"],
        },
    },
    {
        "name": "get_customer_history",
        "description": "Past service history for a client.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "get_travel_matrix",
        "description": "NxN travel minutes matrix for jobs and crews.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_ids": {"type": "array", "items": {"type": "string"}},
                "crew_ids": {"type": "array", "items": {"type": "string"}},
                "force_refresh": {"type": "boolean"},
            },
            "required": ["job_ids", "crew_ids"],
        },
    },
    {
        "name": "check_equipment",
        "description": "Check inventory and crew gear vs job requirements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_ids": {"type": "array", "items": {"type": "string"}},
                "crew_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["job_ids"],
        },
    },
    {
        "name": "run_optimizer",
        "description": "Run OR-Tools VRP for a day; returns routes and assignments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_date": {"type": "string"},
                "job_ids": {"type": "array", "items": {"type": "string"}},
                "crew_ids": {"type": "array", "items": {"type": "string"}},
                "time_limit_seconds": {"type": "integer"},
            },
            "required": ["target_date", "job_ids"],
        },
    },
    {
        "name": "save_schedule_attempt",
        "description": "Persist optimizer result to schedule_attempts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_date": {"type": "string"},
                "job_ids": {"type": "array", "items": {"type": "string"}},
                "crew_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["target_date", "job_ids", "crew_ids"],
        },
    },
    {
        "name": "critique_schedule",
        "description": "Run deterministic + LLM critic on the last saved attempt. Hard gate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_date": {"type": "string"},
                "schedule_attempt_id": {"type": "string"},
            },
            "required": ["target_date"],
        },
    },
    {
        "name": "get_previous_critic_feedback",
        "description": "Prior critic notes for an attempt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schedule_attempt_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["schedule_attempt_id"],
        },
    },
]


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def execute_tool(name: str, tool_input: dict[str, Any], ctx: OrchestratorContext) -> dict[str, Any]:
    """Dispatch a tool call and return JSON-serializable result."""
    ctx.tool_log.append({"tool": name, "input": tool_input})

    if name == "get_crew_availability":
        out = get_crew_availability(
            GetCrewAvailabilityInput(
                target_date=_parse_date(tool_input["target_date"]),
                crew_ids=tool_input.get("crew_ids"),
            )
        )
        available = [c.crew_id for c in out.crews if c.is_available]
        if available and not ctx.crew_ids:
            ctx.crew_ids = available
        return out.model_dump(mode="json")

    if name == "get_weather":
        return get_weather(
            GetWeatherInput(
                lat=float(tool_input["lat"]),
                lng=float(tool_input["lng"]),
                forecast_date=_parse_date(tool_input["forecast_date"]),
            )
        ).model_dump(mode="json")

    if name == "get_customer_history":
        return get_customer_history(
            GetCustomerHistoryInput(
                client_id=tool_input["client_id"],
                limit=int(tool_input.get("limit", 10)),
            )
        ).model_dump(mode="json")

    if name == "get_travel_matrix":
        return get_travel_matrix(
            GetTravelMatrixInput(
                job_ids=tool_input["job_ids"],
                crew_ids=tool_input.get("crew_ids") or ctx.crew_ids,
            )
        ).model_dump(mode="json")

    if name == "check_equipment":
        return check_equipment(
            CheckEquipmentInput(
                job_ids=tool_input["job_ids"],
                crew_ids=tool_input.get("crew_ids") or ctx.crew_ids,
            )
        ).model_dump(mode="json")

    if name == "run_optimizer":
        job_ids = tool_input["job_ids"]
        crew_ids = tool_input.get("crew_ids") or ctx.crew_ids
        ctx.job_ids = job_ids
        ctx.crew_ids = crew_ids
        out = run_optimizer(
            RunOptimizerInput(
                target_date=_parse_date(tool_input["target_date"]),
                job_ids=job_ids,
                crew_ids=crew_ids,
                time_limit_seconds=int(tool_input.get("time_limit_seconds", 15)),
            )
        )
        ctx.last_optimizer_output = out
        return out.model_dump(mode="json")

    if name == "save_schedule_attempt":
        if not ctx.last_optimizer_output:
            raise ValueError("Call run_optimizer before save_schedule_attempt")
        target = _parse_date(tool_input["target_date"])
        job_ids = tool_input["job_ids"]
        crew_ids = tool_input["crew_ids"]
        saved = save_schedule_attempt(
            SaveScheduleAttemptInput(
                target_date=target,
                job_ids=job_ids,
                crew_ids=crew_ids,
                optimizer_input=ctx.last_optimizer_output.optimizer_input,
                result=ctx.last_optimizer_output.result,
            )
        )
        ctx.last_save_output = saved
        _track_best_attempt(ctx, saved.attempt_id)
        return saved.model_dump(mode="json")

    if name == "critique_schedule":
        if not ctx.last_optimizer_output or not ctx.last_save_output:
            raise ValueError("Call run_optimizer and save_schedule_attempt before critique_schedule")
        attempt_id = tool_input.get("schedule_attempt_id")
        if attempt_id:
            attempt_uuid = UUID(attempt_id)
        else:
            attempt_uuid = ctx.last_save_output.attempt_id
        review = review_schedule(
            ReviewScheduleInput(
                target_date=_parse_date(tool_input["target_date"]),
                optimizer_input=ctx.last_optimizer_output.optimizer_input,
                optimizer_result=ctx.last_optimizer_output.result,
                schedule_attempt_id=attempt_uuid,
                persist=True,
                use_llm=ctx.use_llm_critic,
            )
        )
        ctx.last_critique_approved = review.verdict.approved
        ctx.last_critique_issues = list(review.verdict.issues)
        ctx.last_critic_feedback_id = review.critic_feedback_id
        if not review.verdict.approved:
            ctx.critic_feedback = review.verdict.feedback_prompt
        result = {
            "approved": review.verdict.approved,
            "issues": review.verdict.issues,
            "feedback_prompt": review.verdict.feedback_prompt,
            "metrics": review.metrics.model_dump(mode="json"),
            "critic_feedback_id": str(review.critic_feedback_id) if review.critic_feedback_id else None,
            "schedule_attempt_id": str(attempt_uuid),
        }
        return result

    if name == "get_previous_critic_feedback":
        return get_previous_critic_feedback(
            GetPreviousCriticFeedbackInput(
                schedule_attempt_id=UUID(tool_input["schedule_attempt_id"]),
                limit=int(tool_input.get("limit", 3)),
            )
        ).model_dump(mode="json")

    raise ValueError(f"Unknown tool: {name}")


def _track_best_attempt(ctx: OrchestratorContext, attempt_id: UUID) -> None:
    if not ctx.last_optimizer_output:
        return
    fill = len(ctx.last_optimizer_output.result.assigned_job_ids) / max(
        1, len(ctx.job_ids)
    )
    if fill >= ctx.best_fill_score:
        ctx.best_fill_score = fill
        ctx.best_attempt_id = attempt_id

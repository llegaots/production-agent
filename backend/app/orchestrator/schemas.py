"""Orchestrator I/O models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ScheduleRunStatus = Literal[
    "running", "approved", "rejected", "needs_human_review", "failed"
]


class ScheduleWeekInput(BaseModel):
    user_request: str
    week_start: date | None = None
    week_end: date | None = None
    max_iterations: int | None = None
    use_llm_critic: bool = True
    use_agent: bool = Field(
        default=True,
        description="If false, run deterministic tool sequence (no Anthropic API calls)",
    )


class ScheduleIterationSummary(BaseModel):
    iteration_number: int
    schedule_attempt_id: UUID | None = None
    critic_feedback_id: UUID | None = None
    approved: bool
    issues: list[str] = Field(default_factory=list)
    feedback_prompt: str = ""


class ScheduleRunResult(BaseModel):
    schedule_run_id: UUID
    status: ScheduleRunStatus
    approved: bool
    iteration_count: int
    week_start: date
    week_end: date
    iterations: list[ScheduleIterationSummary] = Field(default_factory=list)
    best_schedule_attempt_id: UUID | None = None
    final_schedule_attempt_id: UUID | None = None
    langfuse_trace_id: str | None = None
    summary: str = ""
    needs_human_review: bool = False
    created_at: datetime | None = None
    completed_at: datetime | None = None
    final_output: dict[str, Any] = Field(default_factory=dict)

"""Mutable state shared across orchestrator tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.tools.schemas import RunOptimizerOutput, SaveScheduleAttemptOutput


@dataclass
class OrchestratorContext:
    schedule_run_id: UUID
    user_request: str
    week_start: date
    week_end: date
    job_ids: list[str] = field(default_factory=list)
    crew_ids: list[str] = field(default_factory=list)
    current_iteration: int = 1
    max_iterations: int = 4
    critic_feedback: str = ""
    last_optimizer_output: RunOptimizerOutput | None = None
    last_save_output: SaveScheduleAttemptOutput | None = None
    last_critique_approved: bool | None = None
    last_critique_issues: list[str] = field(default_factory=list)
    last_critic_feedback_id: UUID | None = None
    best_attempt_id: UUID | None = None
    best_fill_score: float = 0.0
    use_llm_critic: bool = True
    tool_log: list[dict[str, Any]] = field(default_factory=list)

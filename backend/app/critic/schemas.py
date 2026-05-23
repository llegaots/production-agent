"""Pydantic models for the schedule critic."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.optimizer.models import OptimizerInput, OptimizerResult


class JobCoordinate(BaseModel):
    job_id: str
    lat: float
    lng: float


class CrewDayMetrics(BaseModel):
    crew_id: str
    target_date: date
    drive_minutes: int = 0
    geographic_spread_km: float = Field(
        0,
        description="Combined stddev of lat/lng in degrees × ~111 km/deg",
    )
    job_count: int = 0


class DeterministicMetrics(BaseModel):
    crew_days: list[CrewDayMetrics] = Field(default_factory=list)
    preference_violation_count: int = 0
    week_fill_score: float = Field(ge=0, le=1, description="Share of input jobs scheduled")
    equipment_fit_score: float = Field(ge=0, le=1, description="Share of assignments with gear fit")
    deterministic_issues: list[str] = Field(
        default_factory=list,
        description="Rule-based flags before LLM review",
    )


class CriticVerdict(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    feedback_prompt: str = ""


class ReviewScheduleInput(BaseModel):
    target_date: date
    optimizer_input: OptimizerInput
    optimizer_result: OptimizerResult
    schedule_attempt_id: UUID | None = None
    job_coordinates: list[JobCoordinate] = Field(
        default_factory=list,
        description="If empty, loaded from Supabase by job id",
    )
    run_history_limit: int = Field(default=3, ge=0, le=10)
    persist: bool = True
    use_llm: bool = True


class ReviewScheduleOutput(BaseModel):
    metrics: DeterministicMetrics
    verdict: CriticVerdict
    critic_feedback_id: UUID | None = None
    reviewer: str
    created_at: datetime | None = None
    run_history_summary: list[dict[str, Any]] = Field(default_factory=list)

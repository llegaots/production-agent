"""Optimizer lab API models."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class OptimizerLabJobUpdate(BaseModel):
    service_type: str | None = None
    address: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=15, le=480)
    earliest_date: date | None = None
    latest_date: date | None = None
    required_skills: list[str] | None = None
    required_equipment: list[str] | None = None
    lat: float | None = None
    lng: float | None = None
    status: str | None = None
    notes: str | None = None


class OptimizerLabRunRequest(BaseModel):
    target_date: date
    job_ids: list[str] = Field(min_length=1)
    crew_ids: list[str] | None = None
    time_limit_seconds: int | None = Field(default=None, ge=1, le=300)


class OptimizerLabRunResponse(BaseModel):
    target_date: str
    status: str
    assigned_count: int
    unassigned_count: int
    assigned_job_ids: list[str]
    unassigned_job_ids: list[str]
    routes: list[dict[str, Any]]
    messages: list[str] = Field(default_factory=list)
    equipment_check: dict[str, Any] | None = None
    duration_seconds: float = 0

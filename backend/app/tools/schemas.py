"""Pydantic input/output models for orchestrator tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.optimizer.models import OptimizerInput, OptimizerResult


# --- Weather ---
class GetWeatherInput(BaseModel):
    lat: float
    lng: float
    forecast_date: date
    force_refresh: bool = False


class WeatherWindow(BaseModel):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)
    suitable_for_exterior_work: bool
    precip_probability: float = Field(ge=0, le=1)
    wind_speed_kmh: float = Field(ge=0)
    summary: str = ""


class GetWeatherOutput(BaseModel):
    lat: float
    lng: float
    forecast_date: date
    provider: Literal["tomorrow_io", "mock", "cache"]
    windows: list[WeatherWindow]
    cached: bool = False
    raw: dict[str, Any] | None = None


# --- Crew availability ---
class GetCrewAvailabilityInput(BaseModel):
    target_date: date
    crew_ids: list[str] | None = None


class CrewAvailabilityRow(BaseModel):
    crew_id: str
    crew_name: str
    is_available: bool
    shift_start_minute: int
    shift_end_minute: int
    unavailable_reason: str = ""
    skills: list[str] = Field(default_factory=list)


class GetCrewAvailabilityOutput(BaseModel):
    target_date: date
    crews: list[CrewAvailabilityRow]


# --- Customer history ---
class GetCustomerHistoryInput(BaseModel):
    client_id: str
    limit: int = Field(default=20, ge=1, le=100)


class ServiceHistoryItem(BaseModel):
    id: UUID
    completed_at: datetime
    service_type: str | None = None
    crew_id: str | None = None
    job_id: str | None = None
    notes: str = ""
    rating: int | None = None


class GetCustomerHistoryOutput(BaseModel):
    client_id: str
    client_name: str
    history: list[ServiceHistoryItem]
    total_visits: int


# --- Travel matrix ---
class TravelNode(BaseModel):
    node_index: int
    ref_id: str
    kind: Literal["depot", "job"]
    lat: float
    lng: float


class GetTravelMatrixInput(BaseModel):
    job_ids: list[str] = Field(min_length=1)
    crew_ids: list[str] = Field(default_factory=list)
    force_refresh: bool = False


class GetTravelMatrixOutput(BaseModel):
    cache_key: str
    nodes: list[TravelNode]
    minutes: list[list[int]]
    provider: Literal["google_maps", "haversine", "cache"]
    cached: bool = False


# --- Optimizer ---
class RunOptimizerInput(BaseModel):
    target_date: date
    job_ids: list[str] = Field(min_length=1)
    crew_ids: list[str] | None = None
    horizon_minutes: int = 600
    time_limit_seconds: int = 15
    force_refresh_travel: bool = False


class RunOptimizerOutput(BaseModel):
    target_date: date
    travel: GetTravelMatrixOutput
    optimizer_input: OptimizerInput
    result: OptimizerResult


# --- Equipment ---
class CheckEquipmentInput(BaseModel):
    job_ids: list[str] = Field(min_length=1)
    crew_ids: list[str] | None = None


class EquipmentConflict(BaseModel):
    job_id: str
    equipment_kind: str
    reason: str


class CheckEquipmentOutput(BaseModel):
    ok: bool
    conflicts: list[EquipmentConflict] = Field(default_factory=list)
    inventory: dict[str, int] = Field(default_factory=dict)
    crew_equipment: dict[str, list[str]] = Field(default_factory=dict)


# --- Schedule attempts ---
class SaveScheduleAttemptInput(BaseModel):
    target_date: date
    job_ids: list[str]
    crew_ids: list[str]
    optimizer_input: OptimizerInput | None = None
    result: OptimizerResult
    messages: list[str] = Field(default_factory=list)


class SaveScheduleAttemptOutput(BaseModel):
    attempt_id: UUID
    created_at: datetime


# --- Critic feedback ---
class GetPreviousCriticFeedbackInput(BaseModel):
    schedule_attempt_id: UUID | None = None
    plan_id: UUID | None = None
    limit: int = Field(default=5, ge=1, le=20)


class CriticFeedbackItem(BaseModel):
    id: UUID | None = None
    source: Literal["critic_feedback", "plan_review"]
    score: int | None = None
    passed: bool | None = None
    concerns: list[str] = Field(default_factory=list)
    narrative: str = ""
    recommendation: str | None = None
    top_concern: str | None = None
    created_at: datetime | None = None


class GetPreviousCriticFeedbackOutput(BaseModel):
    items: list[CriticFeedbackItem]

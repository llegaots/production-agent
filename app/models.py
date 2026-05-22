"""Domain models for ProductionAgent.

These describe the entities a service business cares about when planning
a production week: jobs to perform, crews who perform them, equipment
they need, and the resulting weekly schedule.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ServiceType(str, Enum):
    WINDOW_CLEANING = "window_cleaning"
    PRESSURE_WASHING = "pressure_washing"
    GUTTER_CLEANING = "gutter_cleaning"
    SOLAR_PANEL_CLEANING = "solar_panel_cleaning"
    HIGH_RISE = "high_rise"


class JobStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETE = "complete"


class Skill(str, Enum):
    ROPE_ACCESS = "rope_access"
    LIFT_OPERATOR = "lift_operator"
    PRESSURE_WASH = "pressure_wash"
    LADDER_CERT = "ladder_cert"
    GLASS_RESTORATION = "glass_restoration"


class EquipmentKind(str, Enum):
    PRESSURE_WASHER = "pressure_washer"
    EXTENSION_POLE = "extension_pole"
    WATER_FED_POLE = "water_fed_pole"
    SCISSOR_LIFT = "scissor_lift"
    ROPE_KIT = "rope_kit"
    LADDER_28 = "ladder_28"
    VAN = "van"


class Client(BaseModel):
    id: str
    name: str
    contact_email: str
    contact_phone: str
    preferred_contact: str = "email"
    notes: str = ""


class Equipment(BaseModel):
    id: str
    kind: EquipmentKind
    label: str
    quantity: int = 1


class Crew(BaseModel):
    id: str
    name: str
    members: list[str]
    skills: list[Skill] = Field(default_factory=list)
    daily_minutes: int = 8 * 60
    base_lat: float
    base_lng: float
    equipment_ids: list[str] = Field(default_factory=list)
    hourly_cost: float = 120.0


class Job(BaseModel):
    id: str
    client_id: str
    service_type: ServiceType
    address: str
    lat: float
    lng: float
    estimated_minutes: int
    difficulty: int = Field(ge=1, le=5)
    required_skills: list[Skill] = Field(default_factory=list)
    required_equipment: list[EquipmentKind] = Field(default_factory=list)
    earliest_date: date
    latest_date: date
    price: float = 0.0
    status: JobStatus = JobStatus.PENDING
    notes: str = ""


class ScheduledStop(BaseModel):
    """A job placed in a crew's day with ordering and timing."""

    job_id: str
    order: int
    start_minute: int  # minutes from start of shift (e.g., 0 == start)
    travel_minutes_before: int = 0
    duration_minutes: int


class CrewDay(BaseModel):
    crew_id: str
    day: date
    stops: list[ScheduledStop] = Field(default_factory=list)
    total_drive_minutes: int = 0
    total_work_minutes: int = 0
    utilization: float = 0.0
    overbooked: bool = False
    warnings: list[str] = Field(default_factory=list)


class WeekPlan(BaseModel):
    week_start: date
    days: list[CrewDay] = Field(default_factory=list)
    unscheduled_job_ids: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    summary: str = ""


class AgentEvent(BaseModel):
    """A single step in a multi-agent run, useful for UI streaming."""

    agent: str
    phase: str
    message: str
    detail: Optional[dict] = None


class MessageQuality(BaseModel):
    job_id: str
    score: int
    guardrail_passed: bool
    guardrail_flags: list[str] = Field(default_factory=list)


class PlanReview(BaseModel):
    kpis: dict
    risk_score: int = 0
    top_concern: Optional[str] = None
    recommendation: Optional[str] = None
    narrative: str = ""


class PlanResult(BaseModel):
    plan: WeekPlan
    events: list[AgentEvent] = Field(default_factory=list)
    client_messages: dict[str, str] = Field(default_factory=dict)  # job_id -> message
    message_quality: dict[str, MessageQuality] = Field(default_factory=dict)
    review: Optional[PlanReview] = None


class RescheduleRequest(BaseModel):
    job_id: str
    reason: str
    new_earliest: Optional[date] = None
    new_latest: Optional[date] = None


class RescheduleResult(BaseModel):
    job_id: str
    succeeded: bool
    new_day: Optional[date] = None
    new_crew_id: Optional[str] = None
    client_message: str = ""
    events: list[AgentEvent] = Field(default_factory=list)


class ImportParseRequest(BaseModel):
    text: str


class ImportConfirmRequest(BaseModel):
    rows: list[dict]
    address_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Map row_index (string) -> user-confirmed formatted address",
    )

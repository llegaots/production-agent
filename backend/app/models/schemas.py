"""Pydantic models mirroring public schema (clients = customers in product docs)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ServiceType = Literal[
    "window_cleaning",
    "pressure_washing",
    "gutter_cleaning",
    "solar_panel_cleaning",
    "high_rise",
]
JobStatus = Literal[
    "pending",
    "scheduled",
    "confirmed",
    "rescheduled",
    "cancelled",
    "complete",
]
PreferredContact = Literal["email", "phone", "sms"]


class Client(BaseModel):
    """Customer record (`clients` table)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    contact_email: str
    contact_phone: str
    preferred_contact: PreferredContact = "email"
    notes: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Crew(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    members: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    daily_minutes: int = 480
    base_lat: float
    base_lng: float
    hourly_cost: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CrewSkill(BaseModel):
    crew_id: str
    skill: str


class Equipment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    label: str
    quantity: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    service_type: ServiceType
    address: str
    lat: float
    lng: float
    estimated_minutes: int
    difficulty: int = Field(ge=1, le=5)
    required_skills: list[str] = Field(default_factory=list)
    required_equipment: list[str] = Field(default_factory=list)
    earliest_date: date
    latest_date: date
    price: Decimal = Decimal("0")
    status: JobStatus = "pending"
    notes: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ServiceHistoryRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: str
    job_id: str | None = None
    crew_id: str | None = None
    service_type: str | None = None
    completed_at: datetime
    notes: str = ""
    rating: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime | None = None

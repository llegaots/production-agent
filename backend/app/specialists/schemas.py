"""Pydantic models for Phase 7 specialists."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.schemas import JobStatus, PreferredContact, ServiceType

ParserMode = Literal["rule", "llm", "hybrid"]
MessageStatus = Literal["draft", "queued", "sent", "failed"]
MessageChannel = Literal["email", "sms", "phone"]


class StructuredJobDraft(BaseModel):
    """Parsed job fields before persistence."""

    client_name: str
    client_id: str | None = None
    service_type: ServiceType = "window_cleaning"
    address: str = ""
    lat: float = 45.5017
    lng: float = -73.5673
    estimated_minutes: int = 90
    difficulty: int = Field(default=2, ge=1, le=5)
    required_skills: list[str] = Field(default_factory=lambda: ["residential"])
    required_equipment: list[str] = Field(default_factory=list)
    earliest_date: date
    latest_date: date
    price: float = 0.0
    status: JobStatus = "pending"
    notes: str = ""
    recurrence_rule: str = ""
    preferred_day_of_week: int | None = Field(default=None, ge=0, le=6)
    create_client_if_missing: bool = True


class IntakeParseInput(BaseModel):
    raw_text: str
    use_llm: bool = True
    reference_date: date | None = None


class IntakeParseResult(BaseModel):
    intake_request_id: UUID
    job_id: str
    client_id: str
    draft: StructuredJobDraft
    parser_mode: ParserMode
    created_at: datetime | None = None


class DraftMessageInput(BaseModel):
    job_id: str
    client_id: str
    plan_id: UUID | None = None
    use_llm: bool = True


class MessageDraft(BaseModel):
    subject: str
    body: str
    channel: MessageChannel = "email"
    score: int = Field(default=0, ge=0, le=100)
    guardrail_passed: bool = False
    guardrail_flags: list[str] = Field(default_factory=list)


class DraftMessageResult(BaseModel):
    client_message_id: UUID
    draft: MessageDraft
    status: MessageStatus = "draft"
    created_at: datetime | None = None


class IntakeToDraftInput(BaseModel):
    raw_text: str
    use_llm_intake: bool = False
    use_llm_messenger: bool = False


class IntakeToDraftResult(BaseModel):
    intake: IntakeParseResult
    message: DraftMessageResult

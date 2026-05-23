"""Chat API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ChatRole = Literal["user", "assistant", "system", "tool"]


class CreateChatSessionRequest(BaseModel):
    title: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PostChatMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    use_orchestrator_agent: bool | None = None


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    sequence_number: int
    role: ChatRole
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: dict[str, Any] | list[dict[str, Any]] | None = None
    schedule_preview: dict[str, Any] | None = None
    schedule_run_id: UUID | None = None
    created_at: datetime


class SchedulePreviewPayload(BaseModel):
    """Structured jsonb for UI schedule cards."""

    type: Literal["schedule_preview"] = "schedule_preview"
    schedule_run_id: UUID
    status: str
    approved: bool
    needs_human_review: bool
    week_start: str
    week_end: str
    iteration_count: int
    summary: str = ""
    attempt_id: str | None = None
    assigned_job_ids: list[str] = Field(default_factory=list)
    unassigned_job_ids: list[str] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class ScheduleDecisionResponse(BaseModel):
    schedule_run_id: UUID
    status: str
    approved: bool
    message: str

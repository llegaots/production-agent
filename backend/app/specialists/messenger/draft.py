"""Draft client notifications (stored only — not sent)."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from anthropic import Anthropic

from app.config import get_settings
from app.specialists.messenger.guardrails import apply_guardrails
from app.specialists.schemas import DraftMessageInput, DraftMessageResult, MessageDraft, MessageStatus
from app.tools._db import tools_db

_DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _load_job_context(job_id: str, client_id: str) -> dict[str, Any]:
    job = tools_db().table("jobs").select("*").eq("id", job_id).single().execute().data
    client = tools_db().table("clients").select("*").eq("id", client_id).single().execute().data
    return {"job": job, "client": client}


def _weekday_label(dow: int | None) -> str:
    if dow is None:
        return "your preferred day"
    return _DAY_LABELS[dow]


def draft_message_rule(ctx: dict[str, Any]) -> MessageDraft:
    job = ctx["job"]
    client = ctx["client"]
    name = client["name"]
    channel = client.get("preferred_contact") or "email"
    if channel not in ("email", "sms", "phone"):
        channel = "email"

    day = _weekday_label(job.get("preferred_day_of_week"))
    recurrence = job.get("recurrence_rule") or ""
    recurring = bool(recurrence) or job.get("preferred_day_of_week") is not None

    if recurring:
        subject = f"Your recurring service — {day}s"
        body = (
            f"Dear {name},\n\n"
            f"Thank you for choosing our window cleaning team. We have set up your "
            f"recurring residential service on {day}s"
        )
        if recurrence:
            body += f" ({recurrence})"
        body += (
            ".\n\n"
            "Our crew will reach out before the first visit with an arrival window. "
            "If you need to skip a week or update access instructions, reply to this "
            "message or call our office at 514-555-0100.\n\n"
            "We look forward to keeping your windows spotless.\n\n"
            "Best regards,\nProduction Agent Scheduling"
        )
    else:
        subject = "Upcoming service confirmation"
        body = (
            f"Dear {name},\n\n"
            f"We have received your service request and scheduled it between "
            f"{job['earliest_date']} and {job['latest_date']}. "
            "We will confirm the exact arrival time shortly.\n\n"
            "Best regards,\nProduction Agent Scheduling"
        )

    draft = MessageDraft(subject=subject, body=body, channel=channel)
    return apply_guardrails(draft)


SYSTEM_PROMPT = """You draft client confirmation messages for a window-cleaning company.

Rules:
- Professional, warm tone
- Do NOT promise discounts, guarantees, or collect payment
- Mention recurring weekday when provided
- Include office callback 514-555-0100
- This is a DRAFT only (not sent yet)

Return ONLY JSON:
{
  "subject": "...",
  "body": "multi-line message",
  "channel": "email|sms|phone"
}"""


def _parse_llm_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text.strip())
    if not match:
        raise ValueError("No JSON in messenger LLM response")
    return json.loads(match.group())


def draft_message_llm(ctx: dict[str, Any]) -> MessageDraft:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return draft_message_rule(ctx)

    client = Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "client": {
                            "name": ctx["client"]["name"],
                            "preferred_contact": ctx["client"].get("preferred_contact"),
                        },
                        "job": {
                            "service_type": ctx["job"]["service_type"],
                            "earliest_date": ctx["job"]["earliest_date"],
                            "latest_date": ctx["job"]["latest_date"],
                            "recurrence_rule": ctx["job"].get("recurrence_rule"),
                            "preferred_day_of_week": ctx["job"].get("preferred_day_of_week"),
                            "address": ctx["job"]["address"],
                        },
                    },
                    indent=2,
                ),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    data = _parse_llm_json(text)
    channel = data.get("channel") or ctx["client"].get("preferred_contact") or "email"
    if channel not in ("email", "sms", "phone"):
        channel = "email"
    draft = MessageDraft(
        subject=str(data.get("subject", "Service confirmation")),
        body=str(data.get("body", "")),
        channel=channel,
    )
    return apply_guardrails(draft)


def draft_client_message(inp: DraftMessageInput) -> MessageDraft:
    ctx = _load_job_context(inp.job_id, inp.client_id)
    if inp.use_llm and get_settings().anthropic_api_key:
        try:
            return draft_message_llm(ctx)
        except Exception:
            return draft_message_rule(ctx)
    return draft_message_rule(ctx)


def persist_client_message(
    inp: DraftMessageInput,
    draft: MessageDraft,
) -> DraftMessageResult:
    row = {
        "plan_id": str(inp.plan_id) if inp.plan_id else None,
        "job_id": inp.job_id,
        "client_id": inp.client_id,
        "message": draft.body,
        "subject": draft.subject,
        "channel": draft.channel,
        "status": "draft",
        "score": draft.score,
        "guardrail_passed": draft.guardrail_passed,
        "guardrail_flags": draft.guardrail_flags,
    }
    resp = tools_db().table("client_messages").insert(row).execute()
    msg_id = UUID(resp.data[0]["id"])
    return DraftMessageResult(
        client_message_id=msg_id,
        draft=draft,
        status="draft",
    )

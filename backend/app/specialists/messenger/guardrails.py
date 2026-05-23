"""Lightweight guardrails for outbound client drafts (not sent yet)."""

from __future__ import annotations

import re

from app.specialists.schemas import MessageDraft

_FORBIDDEN_PATTERNS = [
    (r"\bguarantee\b", "no_guarantee_language"),
    (r"\bfree\b", "no_free_promises"),
    (r"\b100%\s*off\b", "no_discount_claims"),
    (r"\bcredit\s+card\b", "no_payment_collection"),
]


def apply_guardrails(draft: MessageDraft) -> MessageDraft:
    flags: list[str] = []
    combined = f"{draft.subject}\n{draft.body}".lower()

    for pattern, flag in _FORBIDDEN_PATTERNS:
        if re.search(pattern, combined, re.I):
            flags.append(flag)

    if len(draft.body.strip()) < 40:
        flags.append("message_too_short")

    scheduling_hints = ("schedule", "scheduled", "recurring", "service on", "visit", "arrival")
    if not any(hint in combined for hint in scheduling_hints):
        flags.append("missing_scheduling_context")

    passed = len(flags) == 0
    score = 95 if passed else max(40, 95 - 15 * len(flags))
    return draft.model_copy(
        update={
            "guardrail_passed": passed,
            "guardrail_flags": flags,
            "score": score,
        }
    )

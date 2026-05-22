"""MessageGuardrailAgent - compliance + quality check on drafted messages.

Anthropic pattern: **Parallelization (sectioning)**.

This is a small specialist agent that focuses on one thing — *is this
message safe to send?* — independent of the drafting agent. It runs
in parallel with the MessageCriticAgent so that drafting, evaluating
for quality, and screening for compliance are three separate calls
each focused on its own aspect.

It is fully deterministic: violations are returned as structured
flags. The orchestrator decides what to do with them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Job
from ..storage import store


@dataclass
class GuardrailResult:
    job_id: str
    passed: bool
    flags: list[str]


class MessageGuardrailAgent:
    name = "MessageGuardrailAgent"

    @staticmethod
    def check(message: str, job: Job, expected_date: str, expected_window: str) -> GuardrailResult:
        flags: list[str] = []
        m = message or ""
        ml = m.lower()

        # 1) Other-client data leakage: no other client name should appear.
        client = store.get_client(job.client_id)
        for other in store.list_clients():
            if other.id == job.client_id:
                continue
            if other.name and other.name.lower() in ml and len(other.name) > 3:
                flags.append(f"References another client by name: '{other.name}'.")

        # 2) Date promise must match the plan: any month-day mention should be
        # the expected date.
        if expected_date:
            promised_date_present = expected_date.lower() in ml
            # Find any other "Mon, Mmm DD" patterns
            month_pattern = re.compile(
                r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}",
                re.IGNORECASE,
            )
            for found in month_pattern.findall(m):
                if expected_date.lower() not in found.lower():
                    flags.append(f"Mentions a date ('{found}') that isn't the scheduled date.")
            if not promised_date_present:
                flags.append("Does not state the scheduled date.")

        # 3) Time window must be quoted as written (if it was provided).
        if expected_window and expected_window not in m:
            flags.append("Does not state the arrival window.")

        # 4) No price commitments unless they appear in the job record.
        if re.search(r"\$\s?\d{2,}", m):
            if not job.price or f"${int(job.price)}" not in m:
                flags.append("Mentions a dollar figure that isn't the job's quoted price.")

        # 5) Action prompt — message should ask the client to confirm OR
        # offer to reschedule. Otherwise it doesn't drive a reply.
        if not (
            "confirm" in ml or "reschedule" in ml or "reply" in ml or "let us know" in ml
        ):
            flags.append("No clear call to action (confirm / reschedule / reply).")

        # 6) Sanity: not absurdly long.
        if len(m) > 1500:
            flags.append("Message is unusually long (>1500 chars).")

        return GuardrailResult(job_id=job.id, passed=not flags, flags=flags)

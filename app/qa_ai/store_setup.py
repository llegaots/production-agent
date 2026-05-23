"""Prepare a clean Supabase-only store for AI QA — no seed job slop."""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..seed import seed
from ..storage import store
from ..supabase_client import supabase
from .test_job_manager import ensure_supabase_reference_data

log = logging.getLogger(__name__)

# Seed dataset job ID prefixes — QA must NEVER schedule or reference these.
SEED_JOB_PREFIXES = ("job_W", "job_G", "job_P", "job_H", "job_S", "job_0")


def load_reference_data_only() -> None:
    """Load crews/clients/equipment from seed but leave jobs empty."""
    seed(reset=True)
    store.jobs.clear()
    store.latest_plan = None
    store.confirmed_plan = None


def is_seed_job_id(job_id: str) -> bool:
    return any(str(job_id).startswith(p) for p in SEED_JOB_PREFIXES)


def normalize_qa_job_id(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return s
    return s if s.startswith("qa_") else f"qa_{s}"


def normalize_case(case: dict) -> dict:
    """Ensure test_jobs and step job_ids use qa_ prefix consistently."""
    out = dict(case)
    test_jobs = []
    for jd in case.get("test_jobs") or []:
        row = dict(jd)
        raw = str(row.get("id") or row.get("job_id") or "")
        if raw:
            row["id"] = normalize_qa_job_id(raw)
        test_jobs.append(row)
    out["test_jobs"] = test_jobs

    steps = []
    allowed = {j["id"] for j in test_jobs if j.get("id")}
    for step in case.get("steps") or []:
        s = dict(step)
        jid = s.get("job_id")
        if jid:
            s["job_id"] = normalize_qa_job_id(jid)
            if s["job_id"] not in allowed:
                log.warning("step references job_id %s not in test_jobs", jid)
        steps.append(s)
    out["steps"] = steps
    return out


def validate_case(case: dict) -> Optional[str]:
    """Return error message if case is invalid for AI QA."""
    if not case.get("fingerprint"):
        return "Case missing fingerprint"
    test_jobs = case.get("test_jobs") or []
    if not test_jobs:
        return "Case must define test_jobs — AI QA does not use seed jobs (job_W*, job_G*, etc.)"
    if len(test_jobs) > 6:
        return f"Too many test_jobs ({len(test_jobs)}); keep to 2–4"
    for jd in test_jobs:
        if not jd.get("id") and not jd.get("job_id"):
            return "Each test_job needs an id"
        if not jd.get("address"):
            return f"test_job {jd.get('id')} missing address"
    return None


async def purge_supabase_seed_artifacts() -> dict[str, Any]:
    """Remove seed-job plans and job_* / qa_* rows from Supabase."""
    if not supabase.enabled:
        return {"purged": False, "reason": "supabase_disabled"}

    counts: dict[str, str] = {}
    try:
        for table in (
            "scheduled_stops",
            "client_messages",
            "agent_events",
            "plan_reviews",
            "crew_days",
            "plans",
        ):
            try:
                await supabase.delete_all(table)
                counts[table] = "cleared"
            except Exception as exc:
                counts[table] = f"error:{exc}"
                log.warning("purge %s failed: %s", table, exc)

        for prefix in ("job_W%", "job_G%", "job_P%", "job_H%", "job_S%", "qa_%"):
            try:
                await supabase.delete_like("jobs", "id", prefix)
            except Exception as exc:
                log.warning("purge jobs like %s failed: %s", prefix, exc)
        counts["jobs"] = "seed_and_qa_cleared"
    except Exception as exc:
        return {"purged": False, "error": str(exc), "partial": counts}

    return {"purged": True, "tables": counts}


async def prepare_qa_run() -> dict[str, Any]:
    """One-shot prep at the start of an AI QA run."""
    load_reference_data_only()
    purge_result = await purge_supabase_seed_artifacts()
    ref = await ensure_supabase_reference_data()
    return {"reference_sync": ref, "purge": purge_result, "jobs_in_store": len(store.list_jobs())}

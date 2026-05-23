"""Create and destroy QA test jobs in Supabase and the in-memory store.

The QA agent designs custom jobs that match each test scenario. This module
inserts them into Supabase (so the scheduler sees them as real persisted
jobs) and cleans them up afterward.

Job IDs are prefixed ``qa_`` so they are easy to filter out of production
reporting and won't collide with real job IDs.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from ..models import EquipmentKind, Job, JobStatus, ServiceType, Skill
from ..storage import store
from ..supabase_client import supabase


# ── helpers ───────────────────────────────────────────────────────────────────

_SERVICE_ALIASES: dict[str, ServiceType] = {
    "window_cleaning":      ServiceType.WINDOW_CLEANING,
    "window":               ServiceType.WINDOW_CLEANING,
    "gutter_cleaning":      ServiceType.GUTTER_CLEANING,
    "gutter":               ServiceType.GUTTER_CLEANING,
    "pressure_washing":     ServiceType.PRESSURE_WASHING,
    "pressure_wash":        ServiceType.PRESSURE_WASHING,
    "high_rise":            ServiceType.HIGH_RISE,
    "highrise":             ServiceType.HIGH_RISE,
    "solar_panel_cleaning": ServiceType.SOLAR_PANEL_CLEANING,
    "solar":                ServiceType.SOLAR_PANEL_CLEANING,
}

_SKILL_ALIASES: dict[str, Skill] = {
    "rope_access":       Skill.ROPE_ACCESS,
    "rope":              Skill.ROPE_ACCESS,
    "lift_operator":     Skill.LIFT_OPERATOR,
    "lift":              Skill.LIFT_OPERATOR,
    "pressure_wash":     Skill.PRESSURE_WASH,
    "ladder_cert":       Skill.LADDER_CERT,
    "ladder":            Skill.LADDER_CERT,
    "glass_restoration": Skill.GLASS_RESTORATION,
    "glass":             Skill.GLASS_RESTORATION,
}

_EQUIP_ALIASES: dict[str, EquipmentKind] = {
    "pressure_washer":  EquipmentKind.PRESSURE_WASHER,
    "pressure_wash":    EquipmentKind.PRESSURE_WASHER,
    "extension_pole":   EquipmentKind.EXTENSION_POLE,
    "water_fed_pole":   EquipmentKind.WATER_FED_POLE,
    "wfp":              EquipmentKind.WATER_FED_POLE,
    "scissor_lift":     EquipmentKind.SCISSOR_LIFT,
    "lift":             EquipmentKind.SCISSOR_LIFT,
    "rope_kit":         EquipmentKind.ROPE_KIT,
    "rope":             EquipmentKind.ROPE_KIT,
    "ladder_28":        EquipmentKind.LADDER_28,
    "ladder_32":        EquipmentKind.LADDER_32,
    "van":              EquipmentKind.VAN,
}


def _parse_service(raw: str) -> ServiceType:
    return _SERVICE_ALIASES.get(raw.lower().replace("-", "_"),
                                ServiceType.WINDOW_CLEANING)


def _parse_skills(raw: list[str]) -> list[Skill]:
    out = []
    for s in raw:
        sk = _SKILL_ALIASES.get(s.lower().replace("-", "_"))
        if sk and sk not in out:
            out.append(sk)
    return out


def _parse_equip(raw: list[str]) -> list[EquipmentKind]:
    out = []
    for e in raw:
        eq = _EQUIP_ALIASES.get(e.lower().replace("-", "_"))
        if eq and eq not in out:
            out.append(eq)
    return out


def _parse_date(raw: Any, fallback: date) -> date:
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except Exception:
        return fallback


# ── Supabase reference sync ───────────────────────────────────────────────────

async def ensure_supabase_reference_data() -> dict[str, int]:
    """Upsert clients, crews, equipment from the in-memory store so QA job inserts satisfy FK constraints."""
    if not supabase.enabled:
        return {"clients": 0, "crews": 0, "equipment": 0}

    counts = {"clients": 0, "crews": 0, "equipment": 0}
    import logging
    log = logging.getLogger(__name__)

    for client in store.list_clients():
        try:
            await supabase.upsert(
                "clients",
                {
                    "id": client.id,
                    "name": client.name,
                    "contact_email": client.contact_email or "",
                    "contact_phone": client.contact_phone or "",
                    "preferred_contact": client.preferred_contact or "email",
                    "notes": client.notes or "",
                },
            )
            counts["clients"] += 1
        except Exception as exc:
            log.warning("qa reference client upsert failed for %s: %s", client.id, exc)

    for eq in store.list_equipment():
        try:
            await supabase.upsert(
                "equipment",
                {
                    "id": eq.id,
                    "kind": eq.kind.value,
                    "label": eq.label,
                    "quantity": eq.quantity,
                },
            )
            counts["equipment"] += 1
        except Exception as exc:
            log.warning("qa reference equipment upsert failed for %s: %s", eq.id, exc)

    for crew in store.list_crews():
        try:
            await supabase.upsert(
                "crews",
                {
                    "id": crew.id,
                    "name": crew.name,
                    "members": crew.members,
                    "skills": [s.value for s in crew.skills],
                    "daily_minutes": crew.daily_minutes,
                    "base_lat": crew.base_lat,
                    "base_lng": crew.base_lng,
                    "hourly_cost": crew.hourly_cost,
                },
            )
            counts["crews"] += 1
        except Exception as exc:
            log.warning("qa reference crew upsert failed for %s: %s", crew.id, exc)

    return counts


# ── public API ────────────────────────────────────────────────────────────────

def build_test_job(job_def: dict, run_id: str, week_start: date) -> Optional[Job]:
    """Construct a Job from a case designer dict.  Returns None on bad input."""
    raw_id = str(job_def.get("id") or job_def.get("job_id") or "")
    if not raw_id:
        return None

    # Ensure ID is prefixed with qa_ so cleanup is reliable.
    job_id = raw_id if raw_id.startswith("qa_") else f"qa_{raw_id}"

    # Ensure client_id maps to a real client; default to first in store.
    client_id = str(job_def.get("client_id") or "")
    if client_id not in store.clients:
        clients = store.list_clients()
        client_id = clients[0].id if clients else "cli_001"

    # Date window: designer specifies "earliest_date"/"latest_date"; fall back
    # to the planning week so the job always lands within the scheduler window.
    earliest = _parse_date(job_def.get("earliest_date"), week_start)
    latest   = _parse_date(job_def.get("latest_date"),   week_start.replace(day=week_start.day + 4))

    # Guard: clamp to within the planning week to ensure scheduler sees it.
    week_end = week_start.replace(day=week_start.day + 4)
    if earliest < week_start:
        earliest = week_start
    if latest > week_end:
        latest = week_end
    if earliest > latest:
        latest = week_end

    try:
        job = Job(
            id=job_id,
            client_id=client_id,
            service_type=_parse_service(job_def.get("service_type", "window_cleaning")),
            address=str(job_def.get("address", "Test address, Montreal QC")),
            lat=float(job_def.get("lat", 45.45)),
            lng=float(job_def.get("lng", -73.87)),
            estimated_minutes=int(job_def.get("estimated_minutes", 90)),
            difficulty=min(5, max(1, int(job_def.get("difficulty", 2)))),
            required_skills=_parse_skills(job_def.get("required_skills") or []),
            required_equipment=_parse_equip(job_def.get("required_equipment") or []),
            earliest_date=earliest,
            latest_date=latest,
            price=float(job_def.get("price", 200.0)),
            notes=f"[QA test job / run {run_id}] " + str(job_def.get("notes", "")),
        )
        job.status = JobStatus.PENDING
        return job
    except Exception as exc:
        return None


async def insert_test_jobs(
    job_defs: list[dict],
    run_id: str,
    week_start: date,
) -> list[str]:
    """Build jobs from definitions, write to store + Supabase. Returns inserted IDs."""
    if supabase.enabled:
        await ensure_supabase_reference_data()

    inserted: list[str] = []
    for jd in job_defs:
        job = build_test_job(jd, run_id, week_start)
        if not job:
            continue

        # Write to in-memory store.
        store.jobs[job.id] = job

        # Write to Supabase if configured.
        if supabase.enabled:
            try:
                # required_skills / required_equipment are text[] in Postgres —
                # pass as plain Python lists; httpx serialises them as JSON arrays
                # which PostgREST accepts for text[] columns.
                await supabase.upsert(
                    "jobs",
                    {
                        "id": job.id,
                        "client_id": job.client_id,
                        "service_type": job.service_type.value,
                        "address": job.address,
                        "lat": job.lat,
                        "lng": job.lng,
                        "estimated_minutes": job.estimated_minutes,
                        "difficulty": job.difficulty,
                        "required_skills":    [s.value for s in job.required_skills],
                        "required_equipment": [e.value for e in job.required_equipment],
                        "earliest_date": job.earliest_date.isoformat(),
                        "latest_date":   job.latest_date.isoformat(),
                        "price":  job.price,
                        "status": job.status.value,
                        "notes":  job.notes,
                    },
                )
            except Exception as exc:
                # Supabase write failure is non-fatal; in-memory store is sufficient.
                import logging
                logging.getLogger(__name__).warning(
                    "qa test_job supabase upsert failed for %s: %s", job.id, exc
                )

        inserted.append(job.id)
    return inserted


async def delete_test_jobs(job_ids: list[str]) -> None:
    """Remove QA test jobs from store and Supabase (including dependent rows)."""
    qa_ids = [jid for jid in job_ids if jid.startswith("qa_")]
    for job_id in job_ids:
        store.jobs.pop(job_id, None)

    if not supabase.enabled or not qa_ids:
        return

    import logging
    log = logging.getLogger(__name__)

    try:
        # Delete dependent rows first (FK constraints on jobs).
        for table in ("scheduled_stops", "client_messages", "agent_events"):
            try:
                await supabase.delete_where(table, "job_id", qa_ids)
            except Exception as exc:
                log.warning("qa cleanup %s delete failed: %s", table, exc)
        await supabase.delete_where("jobs", "id", qa_ids)
    except Exception as exc:
        log.warning("qa test_job supabase delete failed: %s", exc)

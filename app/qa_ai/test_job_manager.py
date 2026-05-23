"""Create and persist QA test jobs in Supabase and the in-memory store.

The QA agent designs custom jobs that match each test scenario. New jobs are
inserted into Supabase (address-only; geocoded at plan time) and kept across
runs so the pool grows for future scenarios.

Job IDs are prefixed ``qa_`` so they are easy to filter out of production
reporting and won't collide with real job IDs.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from ..geocode import geocoder, extract_municipality_hint, municipality_centroid
from ..models import EquipmentKind, Job, JobStatus, ServiceType, Skill
from ..storage import store
from ..supabase_client import supabase
from ..supabase_store import persist_job_location


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


def _normalize_address(addr: str) -> str:
    return " ".join(str(addr or "").lower().split())


def _job_from_supabase_row(row: dict) -> Job:
    earliest = _parse_date(row.get("earliest_date"), date.today())
    latest = _parse_date(row.get("latest_date"), date.today())
    return Job(
        id=row["id"],
        client_id=row["client_id"],
        service_type=_parse_service(row.get("service_type", "window_cleaning")),
        address=row["address"],
        lat=float(row.get("lat") or 0.0),
        lng=float(row.get("lng") or 0.0),
        estimated_minutes=int(row.get("estimated_minutes") or 90),
        difficulty=int(row.get("difficulty") or 2),
        required_skills=_parse_skills(row.get("required_skills") or []),
        required_equipment=_parse_equip(row.get("required_equipment") or []),
        earliest_date=earliest,
        latest_date=latest,
        price=float(row.get("price") or 0),
        status=JobStatus(row.get("status") or "pending"),
        notes=row.get("notes") or "",
    )


def list_qa_jobs_in_store() -> list[Job]:
    return [j for j in store.list_jobs() if j.id.startswith("qa_")]


def existing_qa_job_catalog() -> list[dict[str, str]]:
    """Summary of persisted QA jobs — passed to the case designer to avoid duplicates."""
    return [{"id": j.id, "address": j.address} for j in list_qa_jobs_in_store()]


def existing_qa_job_ids() -> set[str]:
    return {j.id for j in list_qa_jobs_in_store()}


def existing_qa_addresses() -> set[str]:
    return {_normalize_address(j.address) for j in list_qa_jobs_in_store()}


async def hydrate_qa_jobs_from_supabase() -> int:
    """Load qa_* jobs from Supabase into the in-memory store (keeps other store data)."""
    if not supabase.enabled:
        return 0
    import logging
    log = logging.getLogger(__name__)
    try:
        rows = await supabase.select("jobs", filters={"id": "like.qa_%"})
    except Exception as exc:
        log.warning("qa hydrate jobs failed: %s", exc)
        return 0
    for row in rows:
        try:
            store.jobs[row["id"]] = _job_from_supabase_row(row)
        except Exception as exc:
            log.warning("qa hydrate skip %s: %s", row.get("id"), exc)
    return len(rows)


# West Island neighbourhood centroids — delegate to geocode module.
def _neighborhood_fallback(address: str) -> tuple[float, float] | None:
    hint = extract_municipality_hint(address)
    if hint:
        return municipality_centroid(hint)
    return None


async def geocode_test_job(job: Job) -> dict[str, Any]:
    """Verify job address via Google Geocoding; persist coords to store + Supabase."""
    import logging
    log = logging.getLogger(__name__)

    result = await geocoder.geocode(job.address)
    record: dict[str, Any] = {
        "job_id": job.id,
        "input_address": job.address,
        **result.to_dict(),
    }

    if result.success and result.lat is not None and result.lng is not None:
        job.lat = result.lat
        job.lng = result.lng
        if result.formatted_address:
            job.address = result.formatted_address
        conf = int(result.confidence * 100)
        job.notes = (job.notes or "").rstrip() + f" [geocoded {conf}% via {result.source}]"
    else:
        fb = _neighborhood_fallback(job.address)
        if fb:
            job.lat, job.lng = fb
            record["fallback_neighborhood"] = True
            record["lat"] = job.lat
            record["lng"] = job.lng
            record["success"] = True
            record["source"] = "neighborhood_fallback"
            record["needs_review"] = True
            job.notes = (job.notes or "").rstrip() + " [geocode fallback: neighbourhood centroid]"
            log.warning("qa geocode failed for %s — using neighbourhood fallback", job.id)
        else:
            log.warning("qa geocode failed for %s: %s", job.id, result.issues)

    store.jobs[job.id] = job
    if supabase.enabled and (result.success or record.get("fallback_neighborhood")):
        try:
            await persist_job_location(
                job.id,
                job.lat,
                job.lng,
                job.address,
                geocode_confidence=result.confidence if result.success else 0.5,
            )
        except Exception as exc:
            log.warning("qa persist_job_location failed for %s: %s", job.id, exc)

    record["final_lat"] = job.lat
    record["final_lng"] = job.lng
    record["final_address"] = job.address
    return record


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
            lat=0.0,
            lng=0.0,
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
) -> tuple[list[str], list[dict[str, Any]]]:
    """Insert new address-only QA jobs; skip ids already in store/Supabase.

    Coordinates are resolved later by GeoClusterAgent during plan from the
    street address. Returns (case_job_ids, empty geocode_log placeholder).
    """
    if supabase.enabled:
        await ensure_supabase_reference_data()

    case_job_ids: list[str] = []
    skipped_existing: list[str] = []
    known_addrs = existing_qa_addresses()

    for jd in job_defs:
        job = build_test_job(jd, run_id, week_start)
        if not job:
            continue

        if job.id in store.jobs:
            case_job_ids.append(job.id)
            skipped_existing.append(job.id)
            continue

        addr_key = _normalize_address(job.address)
        if addr_key in known_addrs:
            import logging
            logging.getLogger(__name__).warning(
                "qa skip duplicate address for new job %s: %s", job.id, job.address
            )
            continue

        job.notes = (job.notes or "").rstrip() + " [coords pending geocode]"
        store.jobs[job.id] = job
        known_addrs.add(addr_key)

        if supabase.enabled:
            try:
                await supabase.upsert(
                    "jobs",
                    {
                        "id": job.id,
                        "client_id": job.client_id,
                        "service_type": job.service_type.value,
                        "address": job.address,
                        "lat": 0.0,
                        "lng": 0.0,
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
                import logging
                logging.getLogger(__name__).warning(
                    "qa test_job supabase upsert failed for %s: %s", job.id, exc
                )

        case_job_ids.append(job.id)

    if skipped_existing:
        import logging
        logging.getLogger(__name__).info(
            "qa reused %d existing test jobs: %s", len(skipped_existing), skipped_existing[:5]
        )
    return case_job_ids, []


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

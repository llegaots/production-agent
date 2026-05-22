"""Supabase-backed seeder and writer for the agent system.

Strategy:
  - On startup, if Supabase env vars are configured, hydrate the in-memory
    ``store`` from the database (clients, crews, equipment, jobs).
  - After every plan/reschedule, persist the resulting plan + crew_days +
    scheduled_stops + client_messages + plan_review + agent_events back to
    Supabase.

The in-memory ``store`` remains the canonical source for agents in-process
(it's fast and synchronous). Supabase is the durable backing store and the
audit log.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from .models import (
    AgentEvent,
    Client,
    Crew,
    Equipment,
    EquipmentKind,
    Job,
    JobStatus,
    PlanResult,
    ServiceType,
    Skill,
)
from .storage import store
from .supabase_client import supabase


# ----- read / hydrate -----

async def hydrate_from_supabase() -> dict:
    """Pull clients, crews, equipment, jobs into the in-memory store."""
    if not supabase.enabled:
        return {"hydrated": False, "reason": "SUPABASE_URL or service-role key not set."}

    clients = await supabase.select("clients")
    crews_rows = await supabase.select("crews")
    equipment_rows = await supabase.select("equipment")
    loadouts = await supabase.select("crew_equipment")
    jobs_rows = await supabase.select("jobs")

    store.clients.clear()
    store.crews.clear()
    store.equipment.clear()
    store.jobs.clear()
    store.latest_plan = None

    for c in clients:
        store.clients[c["id"]] = Client(**c)

    for e in equipment_rows:
        store.equipment[e["id"]] = Equipment(
            id=e["id"], kind=EquipmentKind(e["kind"]), label=e["label"], quantity=e["quantity"]
        )

    loadout_by_crew: dict[str, list[str]] = {}
    for row in loadouts:
        loadout_by_crew.setdefault(row["crew_id"], []).append(row["equipment_id"])

    for c in crews_rows:
        store.crews[c["id"]] = Crew(
            id=c["id"],
            name=c["name"],
            members=list(c.get("members") or []),
            skills=[Skill(s) for s in (c.get("skills") or [])],
            daily_minutes=c["daily_minutes"],
            base_lat=c["base_lat"],
            base_lng=c["base_lng"],
            equipment_ids=loadout_by_crew.get(c["id"], []),
            hourly_cost=float(c["hourly_cost"]),
        )

    for j in jobs_rows:
        store.jobs[j["id"]] = Job(
            id=j["id"],
            client_id=j["client_id"],
            service_type=ServiceType(j["service_type"]),
            address=j["address"],
            lat=j["lat"],
            lng=j["lng"],
            estimated_minutes=j["estimated_minutes"],
            difficulty=j["difficulty"],
            required_skills=[Skill(s) for s in (j.get("required_skills") or [])],
            required_equipment=[EquipmentKind(e) for e in (j.get("required_equipment") or [])],
            earliest_date=_to_date(j["earliest_date"]),
            latest_date=_to_date(j["latest_date"]),
            price=float(j.get("price") or 0),
            status=JobStatus(j["status"]),
            notes=j.get("notes") or "",
        )

    return {
        "hydrated": True,
        "clients": len(store.list_clients()),
        "crews": len(store.list_crews()),
        "equipment": len(store.list_equipment()),
        "jobs": len(store.list_jobs()),
    }


# ----- write / persist -----

async def persist_plan(result: PlanResult) -> Optional[str]:
    """Persist a PlanResult to Supabase. Returns the plan UUID, or None if disabled."""
    if not supabase.enabled:
        return None

    plan = result.plan
    plan_row = (
        await supabase.insert(
            "plans",
            {
                "week_start": plan.week_start.isoformat(),
                "summary": plan.summary,
                "conflicts": plan.conflicts,
                "unscheduled_job_ids": plan.unscheduled_job_ids,
            },
        )
    )[0]
    plan_id = plan_row["id"]

    # crew_days + stops
    for cd in plan.days:
        cd_row = (
            await supabase.insert(
                "crew_days",
                {
                    "plan_id": plan_id,
                    "crew_id": cd.crew_id,
                    "day": cd.day.isoformat(),
                    "total_drive_minutes": cd.total_drive_minutes,
                    "total_work_minutes": cd.total_work_minutes,
                    "utilization": float(cd.utilization),
                    "overbooked": cd.overbooked,
                    "warnings": cd.warnings,
                },
            )
        )[0]
        if cd.stops:
            await supabase.insert(
                "scheduled_stops",
                [
                    {
                        "crew_day_id": cd_row["id"],
                        "job_id": s.job_id,
                        "stop_order": s.order,
                        "start_minute": s.start_minute,
                        "travel_minutes_before": s.travel_minutes_before,
                        "duration_minutes": s.duration_minutes,
                    }
                    for s in cd.stops
                ],
            )

    # client_messages with quality
    msgs_payload = []
    for jid, msg in result.client_messages.items():
        q = result.message_quality.get(jid)
        msgs_payload.append(
            {
                "plan_id": plan_id,
                "job_id": jid,
                "message": msg,
                "score": q.score if q else 0,
                "guardrail_passed": q.guardrail_passed if q else True,
                "guardrail_flags": q.guardrail_flags if q else [],
            }
        )
    if msgs_payload:
        await supabase.insert("client_messages", msgs_payload)

    # plan_review
    if result.review:
        await supabase.insert(
            "plan_reviews",
            {
                "plan_id": plan_id,
                "kpis": result.review.kpis,
                "risk_score": result.review.risk_score,
                "top_concern": result.review.top_concern,
                "recommendation": result.review.recommendation,
                "narrative": result.review.narrative,
            },
        )

    # agent_events
    if result.events:
        await supabase.insert(
            "agent_events",
            [
                {
                    "plan_id": plan_id,
                    "agent": e.agent,
                    "phase": e.phase,
                    "message": e.message,
                    "detail": e.detail,
                }
                for e in result.events
            ],
        )

    return plan_id


async def persist_job_status(job_id: str, status: JobStatus) -> None:
    if not supabase.enabled:
        return
    await supabase.update("jobs", filters={"id": f"eq.{job_id}"}, patch={"status": status.value})


async def persist_job_location(
    job_id: str,
    lat: float,
    lng: float,
    address: str,
    *,
    geocode_confidence: Optional[float] = None,
) -> None:
    """Write verified coordinates back to Supabase after GeoCluster geocoding."""
    if not supabase.enabled:
        return
    notes_suffix = ""
    if geocode_confidence is not None:
        notes_suffix = f" [geocode {int(geocode_confidence * 100)}%]"
    patch: dict = {"lat": lat, "lng": lng, "address": address}
    # Append confidence hint to notes without overwriting user notes
    job = store.get_job(job_id)
    if job and geocode_confidence is not None:
        base = (job.notes or "").split(" [geocode")[0].strip()
        patch["notes"] = (base + notes_suffix).strip()
    await supabase.update("jobs", filters={"id": f"eq.{job_id}"}, patch=patch)


async def persist_reschedule_events(plan_id: Optional[str], job_id: str, events: list[AgentEvent]) -> None:
    if not supabase.enabled or not events:
        return
    await supabase.insert(
        "agent_events",
        [
            {
                "plan_id": plan_id,
                "job_id": job_id,
                "agent": e.agent,
                "phase": e.phase,
                "message": e.message,
                "detail": e.detail,
            }
            for e in events
        ],
    )


def _to_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])

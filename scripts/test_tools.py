#!/usr/bin/env python3
"""Standalone smoke tests for Phase 4 tools (requires .env + Supabase)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools import (  # noqa: E402
    check_equipment,
    get_crew_availability,
    get_customer_history,
    get_previous_critic_feedback,
    get_travel_matrix,
    get_weather,
    run_optimizer,
    save_schedule_attempt,
)
from app.tools._db import tools_db
from app.tools.schemas import (
    CheckEquipmentInput,
    GetCrewAvailabilityInput,
    GetCustomerHistoryInput,
    GetPreviousCriticFeedbackInput,
    GetTravelMatrixInput,
    GetWeatherInput,
    RunOptimizerInput,
    SaveScheduleAttemptInput,
)


def _sample_ids():
    db = tools_db()
    client = db.table("clients").select("id").limit(1).execute().data[0]
    crew = db.table("crews").select("id").limit(2).execute().data
    jobs = (
        db.table("jobs")
        .select("id")
        .eq("status", "pending")
        .limit(3)
        .execute()
        .data
    )
    return client["id"], [c["id"] for c in crew], [j["id"] for j in jobs]


def main() -> int:
    today = date.today()
    client_id, crew_ids, job_ids = _sample_ids()
    print("Samples:", client_id, crew_ids, job_ids)

    w = get_weather(GetWeatherInput(lat=45.5, lng=-73.57, forecast_date=today))
    print("get_weather:", w.provider, len(w.windows), "windows, cached=", w.cached)

    ca = get_crew_availability(GetCrewAvailabilityInput(target_date=today, crew_ids=crew_ids))
    print("get_crew_availability:", len(ca.crews), "crews")

    ch = get_customer_history(GetCustomerHistoryInput(client_id=client_id, limit=5))
    print("get_customer_history:", ch.client_name, ch.total_visits, "visits")

    tm = get_travel_matrix(GetTravelMatrixInput(job_ids=job_ids, crew_ids=crew_ids))
    print("get_travel_matrix:", tm.provider, len(tm.nodes), "nodes, cached=", tm.cached)

    ce = check_equipment(CheckEquipmentInput(job_ids=job_ids, crew_ids=crew_ids))
    print("check_equipment: ok=", ce.ok, "conflicts=", len(ce.conflicts))

    opt = run_optimizer(
        RunOptimizerInput(
            target_date=today,
            job_ids=job_ids,
            crew_ids=crew_ids,
            time_limit_seconds=5,
        )
    )
    print("run_optimizer:", opt.result.status, "assigned=", len(opt.result.assigned_job_ids))

    saved = save_schedule_attempt(
        SaveScheduleAttemptInput(
            target_date=today,
            job_ids=job_ids,
            crew_ids=crew_ids,
            optimizer_input=opt.optimizer_input,
            result=opt.result,
        )
    )
    print("save_schedule_attempt:", saved.attempt_id)

    db = tools_db()
    db.table("critic_feedback").insert(
        {
            "schedule_attempt_id": str(saved.attempt_id),
            "reviewer": "plan_reviewer",
            "score": 85,
            "passed": True,
            "concerns": ["test concern"],
            "narrative": "Phase 4 smoke test feedback",
        }
    ).execute()

    fb = get_previous_critic_feedback(
        GetPreviousCriticFeedbackInput(schedule_attempt_id=saved.attempt_id, limit=3)
    )
    print("get_previous_critic_feedback:", len(fb.items), "items")

    print("\nOK — all Phase 4 tools executed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FAIL:", exc)
        raise SystemExit(1) from exc

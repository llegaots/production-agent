"""Phase 4 tool tests (live Supabase; skip if credentials missing)."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

pytestmark = pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") and not (ROOT / ".env").is_file(),
    reason="Supabase credentials required",
)


@pytest.fixture(scope="module")
def sample_ids():
    from app.tools._db import tools_db

    db = tools_db()
    client = db.table("clients").select("id").limit(1).execute().data[0]["id"]
    crews = [r["id"] for r in db.table("crews").select("id").limit(2).execute().data]
    jobs = [
        r["id"]
        for r in db.table("jobs").select("id").eq("status", "pending").limit(3).execute().data
    ]
    assert len(jobs) >= 2
    return client, crews, jobs


def test_get_weather():
    from app.tools.weather import get_weather
    from app.tools.schemas import GetWeatherInput

    out = get_weather(GetWeatherInput(lat=45.5017, lng=-73.5673, forecast_date=date.today()))
    assert out.windows
    assert out.provider in ("mock", "tomorrow_io", "cache")


def test_get_crew_availability(sample_ids):
    from app.tools.crew_availability import get_crew_availability
    from app.tools.schemas import GetCrewAvailabilityInput

    _, crews, _ = sample_ids
    out = get_crew_availability(
        GetCrewAvailabilityInput(target_date=date.today(), crew_ids=crews)
    )
    assert len(out.crews) == len(crews)


def test_get_customer_history(sample_ids):
    from app.tools.customer_history import get_customer_history
    from app.tools.schemas import GetCustomerHistoryInput

    client_id, _, _ = sample_ids
    out = get_customer_history(GetCustomerHistoryInput(client_id=client_id))
    assert out.client_id == client_id


def test_get_travel_matrix_cached(sample_ids):
    from app.tools.travel_matrix import get_travel_matrix
    from app.tools.schemas import GetTravelMatrixInput

    _, crews, jobs = sample_ids
    a = get_travel_matrix(GetTravelMatrixInput(job_ids=jobs, crew_ids=crews))
    b = get_travel_matrix(GetTravelMatrixInput(job_ids=jobs, crew_ids=crews))
    assert len(a.minutes) == len(a.nodes)
    assert b.provider in ("cache", "haversine", "google_maps")


def test_check_equipment(sample_ids):
    from app.tools.equipment import check_equipment
    from app.tools.schemas import CheckEquipmentInput

    _, crews, jobs = sample_ids
    out = check_equipment(CheckEquipmentInput(job_ids=jobs, crew_ids=crews))
    assert isinstance(out.ok, bool)


def test_run_optimizer_and_save(sample_ids):
    from app.tools.optimizer_tool import run_optimizer
    from app.tools.schedule_attempts import save_schedule_attempt
    from app.tools.schemas import RunOptimizerInput, SaveScheduleAttemptInput

    _, crews, jobs = sample_ids
    opt = run_optimizer(
        RunOptimizerInput(
            target_date=date.today(),
            job_ids=jobs[:2],
            crew_ids=crews,
            time_limit_seconds=5,
        )
    )
    assert opt.result.status in ("optimal", "feasible", "infeasible")
    saved = save_schedule_attempt(
        SaveScheduleAttemptInput(
            target_date=date.today(),
            job_ids=jobs[:2],
            crew_ids=crews,
            optimizer_input=opt.optimizer_input,
            result=opt.result,
        )
    )
    assert saved.attempt_id


def test_get_previous_critic_feedback(sample_ids):
    from app.tools._db import tools_db
    from app.tools.critic_feedback import get_previous_critic_feedback
    from app.tools.optimizer_tool import run_optimizer
    from app.tools.schedule_attempts import save_schedule_attempt
    from app.tools.schemas import (
        GetPreviousCriticFeedbackInput,
        RunOptimizerInput,
        SaveScheduleAttemptInput,
    )

    _, crews, jobs = sample_ids
    opt = run_optimizer(
        RunOptimizerInput(
            target_date=date.today(),
            job_ids=jobs[:2],
            crew_ids=crews,
            time_limit_seconds=3,
        )
    )
    saved = save_schedule_attempt(
        SaveScheduleAttemptInput(
            target_date=date.today(),
            job_ids=jobs[:2],
            crew_ids=crews,
            result=opt.result,
        )
    )
    tools_db().table("critic_feedback").insert(
        {
            "schedule_attempt_id": str(saved.attempt_id),
            "reviewer": "pytest",
            "score": 90,
            "passed": True,
            "narrative": "test",
        }
    ).execute()
    fb = get_previous_critic_feedback(
        GetPreviousCriticFeedbackInput(schedule_attempt_id=saved.attempt_id)
    )
    assert fb.items

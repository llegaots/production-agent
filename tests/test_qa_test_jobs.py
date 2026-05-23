"""Tests for QA test job lifecycle: Supabase writes, snapshot timing, focused scenarios."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.qa_ai.executor import execute_case
from app.qa_ai.test_job_manager import build_test_job, insert_test_jobs
from app.seed import SEED_WEEK_START, seed
from app.storage import store


def _geo_case():
    return {
        "fingerprint": "geo_routing_focus",
        "title": "Three jobs geo routing",
        "test_jobs": [
            {
                "id": "job_001",
                "service_type": "window_cleaning",
                "address": "100 Lakeshore, Pointe-Claire QC",
                "estimated_minutes": 120,
                "required_skills": ["ladder_cert"],
                "required_equipment": ["ladder_28"],
                "earliest_date": "2026-07-08",
                "latest_date": "2026-07-08",
                "price": 300,
            },
            {
                "id": "job_002",
                "service_type": "gutter_cleaning",
                "address": "50 Elm, Beaconsfield QC",
                "estimated_minutes": 150,
                "required_skills": ["ladder_cert"],
                "required_equipment": ["ladder_32"],
                "earliest_date": "2026-07-08",
                "latest_date": "2026-07-08",
                "price": 400,
            },
            {
                "id": "job_003",
                "service_type": "pressure_washing",
                "address": "75 Hymus, Kirkland QC",
                "estimated_minutes": 100,
                "required_skills": ["pressure_wash"],
                "required_equipment": ["pressure_washer"],
                "earliest_date": "2026-07-08",
                "latest_date": "2026-07-08",
                "price": 350,
            },
        ],
        "steps": [{"action": "plan", "scheduling_mode": "geo_first"}],
    }


def test_build_test_job_adds_qa_prefix():
    seed(reset=True)
    job = build_test_job({"id": "job_001", "service_type": "window_cleaning"}, "run1", SEED_WEEK_START)
    assert job is not None
    assert job.id == "qa_job_001"


def test_execute_case_snapshot_shows_qa_jobs_not_unknown():
    """Regression: test jobs must appear in critic snapshot, not as job_id=unknown."""
    async def _run():
        result = await execute_case(_geo_case(), week_start=SEED_WEEK_START, run_id="test")
        ctx = result.to_dict().get("final_plan") or {}
        unknown = [
            s
            for cd in ctx.get("crew_days", [])
            for s in cd.get("stops", [])
            if s.get("job_id") == "unknown"
        ]
        qa_stops = [
            s.get("job_id")
            for cd in ctx.get("crew_days", [])
            for s in cd.get("stops", [])
            if str(s.get("job_id", "")).startswith("qa_")
        ]
        return unknown, qa_stops, result.inserted_job_ids

    unknown, qa_stops, inserted = asyncio.run(_run())
    assert inserted == ["qa_job_001", "qa_job_002", "qa_job_003"]
    assert unknown == [], f"Expected no unknown stops, got {unknown}"
    assert len(qa_stops) == 3, f"Expected 3 qa stops, got {qa_stops}"


def test_execute_case_focuses_on_test_jobs_only():
    """When test_jobs are defined, seed jobs should not appear in the plan."""
    async def _run():
        result = await execute_case(_geo_case(), week_start=SEED_WEEK_START, run_id="test")
        ctx = result.to_dict().get("final_plan") or {}
        all_ids = [
            s.get("job_id")
            for cd in ctx.get("crew_days", [])
            for s in cd.get("stops", [])
        ]
        return all_ids

    all_ids = asyncio.run(_run())
    assert all(jid.startswith("qa_") for jid in all_ids)
    assert len(all_ids) == 3


def test_insert_test_jobs_upserts_reference_data_before_jobs():
    seed(reset=True)
    upsert_calls: list[tuple[str, dict]] = []

    async def _fake_upsert(table, row):
        upsert_calls.append((table, row if isinstance(row, dict) else row[0]))
        return [row]

    mock_sb = AsyncMock()
    mock_sb.enabled = True
    mock_sb.upsert = AsyncMock(side_effect=_fake_upsert)

    with patch("app.qa_ai.test_job_manager.supabase", mock_sb):
        ids = asyncio.run(
            insert_test_jobs(
                [{"id": "job_001", "service_type": "window_cleaning", "address": "Test QC"}],
                "run_x",
                SEED_WEEK_START,
            )
        )

    assert ids == ["qa_job_001"]
    tables = [t for t, _ in upsert_calls]
    assert "clients" in tables
    assert "jobs" in tables
    assert tables.index("clients") < tables.index("jobs")

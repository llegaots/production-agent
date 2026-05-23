"""Tests for QA test job lifecycle: Supabase writes, snapshot timing, focused scenarios."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.geocode import GeocodeResult
from app.qa_ai.executor import execute_case
from app.qa_ai.test_job_manager import build_test_job, geocode_test_job, insert_test_jobs
from app.seed import SEED_WEEK_START, seed
from app.storage import store


def _mock_geocode_by_address():
    coords = {
        "100 Lakeshore, Pointe-Claire QC": (45.4460, -73.8280),
        "50 Elm, Beaconsfield QC": (45.4340, -73.8620),
        "75 Hymus, Kirkland QC": (45.4530, -73.8700),
        "Test QC": (45.4460, -73.8280),
    }

    async def _geocode(address: str):
        lat, lng = coords.get(address, (45.45, -73.87))
        return GeocodeResult(
            input_address=address,
            success=True,
            lat=lat,
            lng=lng,
            formatted_address=address,
            confidence=0.92,
            needs_review=False,
            in_service_area=True,
            location_type="ROOFTOP",
            postal_code="H9X",
            province="QC",
            source="google",
        )

    return _geocode


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


def test_geocode_test_job_uses_distinct_coordinates():
    seed(reset=True)
    job = build_test_job(
        {"id": "job_001", "service_type": "window_cleaning", "address": "50 Elm, Beaconsfield QC"},
        "run1",
        SEED_WEEK_START,
    )
    assert job is not None

    async def _run():
        with patch("app.qa_ai.test_job_manager.geocoder.geocode", _mock_geocode_by_address()):
            with patch("app.qa_ai.test_job_manager.persist_job_location", AsyncMock()):
                return await geocode_test_job(job)

    record = asyncio.run(_run())
    assert record["success"] is True
    assert record["final_lat"] == 45.4340
    assert record["final_lng"] == -73.8620


def test_insert_test_jobs_defers_geocode_to_plan():
    seed(reset=True)

    async def _run():
        mock_sb = AsyncMock()
        mock_sb.enabled = False
        with patch("app.qa_ai.test_job_manager.supabase", mock_sb):
            return await insert_test_jobs(
                [
                    {"id": "job_001", "service_type": "window_cleaning", "address": "100 Lakeshore, Pointe-Claire QC"},
                    {"id": "job_002", "service_type": "gutter_cleaning", "address": "50 Elm, Beaconsfield QC"},
                ],
                "run_geo",
                SEED_WEEK_START,
            )

    ids, geo_log = asyncio.run(_run())
    assert len(ids) == 2
    assert geo_log == []
    j1 = store.get_job("qa_job_001")
    j2 = store.get_job("qa_job_002")
    assert j1 and j2
    assert j1.lat == 0.0 and j1.lng == 0.0
    assert j2.lat == 0.0 and j2.lng == 0.0
    assert "pending geocode" in (j1.notes or "")


def test_insert_test_jobs_supabase_upsert_has_zero_coords():
    seed(reset=True)
    upsert_rows: list[dict] = []

    async def _fake_upsert(table, row):
        upsert_rows.append({"table": table, **(row if isinstance(row, dict) else row[0])})
        return [row]

    mock_sb = AsyncMock()
    mock_sb.enabled = True
    mock_sb.upsert = AsyncMock(side_effect=_fake_upsert)

    with patch("app.qa_ai.test_job_manager.supabase", mock_sb):
        ids, _ = asyncio.run(
            insert_test_jobs(
                [{"id": "job_001", "service_type": "window_cleaning", "address": "547 Saint-Jean Blvd, Pointe-Claire QC"}],
                "run_x",
                SEED_WEEK_START,
            )
        )

    assert ids == ["qa_job_001"]
    job_rows = [r for r in upsert_rows if r["table"] == "jobs"]
    assert len(job_rows) == 1
    assert job_rows[0]["lat"] == 0.0
    assert job_rows[0]["lng"] == 0.0
    assert "547 Saint-Jean" in job_rows[0]["address"]


def test_build_test_job_ignores_lat_lng_in_def():
    seed(reset=True)
    job = build_test_job(
        {
            "id": "job_001",
            "service_type": "window_cleaning",
            "address": "50 Elm, Beaconsfield QC",
            "lat": 45.99,
            "lng": -73.99,
        },
        "run1",
        SEED_WEEK_START,
    )
    assert job is not None
    assert job.lat == 0.0
    assert job.lng == 0.0


def test_execute_case_snapshot_shows_qa_jobs_not_unknown():
    """Regression: test jobs must appear in critic snapshot, not as job_id=unknown."""
    async def _run():
        with patch("app.qa_ai.test_job_manager.geocoder.geocode", _mock_geocode_by_address()):
            with patch("app.agents.geo_cluster.geocoder.geocode", _mock_geocode_by_address()):
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
        with patch("app.qa_ai.test_job_manager.geocoder.geocode", _mock_geocode_by_address()):
            with patch("app.agents.geo_cluster.geocoder.geocode", _mock_geocode_by_address()):
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
        with patch("app.qa_ai.test_job_manager.geocoder.geocode", _mock_geocode_by_address()):
            ids, _ = asyncio.run(
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

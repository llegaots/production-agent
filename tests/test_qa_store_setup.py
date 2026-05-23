"""Tests for Supabase-only QA store setup."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.qa_ai.store_setup import (
    is_seed_job_id,
    load_reference_data_only,
    normalize_case,
    validate_case,
    validate_case_designer_output,
    validate_case_no_duplicate_jobs,
)
from app.storage import store


def test_is_seed_job_id():
    assert is_seed_job_id("job_W05")
    assert is_seed_job_id("job_H02")
    assert not is_seed_job_id("qa_job_001")


def test_load_reference_data_only_has_no_jobs():
    load_reference_data_only()
    assert len(store.list_jobs()) == 0
    assert len(store.list_crews()) >= 3
    assert len(store.list_clients()) >= 1


def test_normalize_case_adds_qa_prefix():
    case = normalize_case({
        "test_jobs": [{"id": "job_001", "address": "x"}],
        "steps": [{"action": "reschedule", "job_id": "job_001"}],
    })
    assert case["test_jobs"][0]["id"] == "qa_job_001"
    assert case["steps"][0]["job_id"] == "qa_job_001"


def test_validate_case_rejects_missing_test_jobs():
    err = validate_case({"fingerprint": "x", "test_jobs": []})
    assert err is not None
    assert "test_jobs" in err


def test_validate_case_accepts_valid_case(monkeypatch):
    monkeypatch.setenv("QA_MIN_TEST_JOBS", "1")
    err = validate_case({
        "fingerprint": "geo_test",
        "test_jobs": [
            {"id": "job_001", "address": "100 Main, Kirkland QC", "service_type": "window_cleaning"}
        ],
    })
    assert err is None


def test_validate_case_rejects_lat_lng():
    err = validate_case_designer_output({
        "test_jobs": [
            {
                "id": "job_001",
                "address": "100 Main, Kirkland QC",
                "lat": 45.45,
                "lng": -73.87,
            }
        ],
    })
    assert err is not None
    assert "lat/lng" in err


def test_normalize_case_strips_lat_lng():
    case = normalize_case({
        "test_jobs": [{"id": "job_001", "address": "x", "lat": 1.0, "lng": 2.0}],
    })
    assert "lat" not in case["test_jobs"][0]
    assert "lng" not in case["test_jobs"][0]


def test_purge_supabase_seed_artifacts():
    mock_sb = AsyncMock()
    mock_sb.enabled = True
    mock_sb.delete_all = AsyncMock()
    mock_sb.delete_like = AsyncMock()

    with patch("app.qa_ai.store_setup.supabase", mock_sb):
        result = asyncio.run(__import__("app.qa_ai.store_setup", fromlist=["purge_supabase_seed_artifacts"]).purge_supabase_seed_artifacts())

    assert result["purged"] is True
    assert mock_sb.delete_all.call_count >= 6
    like_patterns = [c.args[2] for c in mock_sb.delete_like.call_args_list if c.args[0] == "jobs"]
    assert like_patterns
    assert not any(p.startswith("qa_") for p in like_patterns)
    assert result["tables"]["jobs"] == "seed_cleared_qa_retained"


def test_validate_case_rejects_duplicate_qa_job(monkeypatch):
    monkeypatch.setenv("QA_MIN_TEST_JOBS", "1")
    from app.models import Job, JobStatus, ServiceType
    from app.seed import SEED_WEEK_START

    load_reference_data_only()
    store.jobs["qa_job_001"] = Job(
        id="qa_job_001",
        client_id="cli_001",
        service_type=ServiceType.WINDOW_CLEANING,
        address="100 Main, Kirkland QC",
        lat=0.0,
        lng=0.0,
        estimated_minutes=90,
        difficulty=2,
        earliest_date=SEED_WEEK_START,
        latest_date=SEED_WEEK_START,
        status=JobStatus.PENDING,
    )
    err = validate_case_no_duplicate_jobs({
        "test_jobs": [{"id": "job_001", "address": "200 Other, Beaconsfield QC"}],
    })
    assert err is not None
    assert "already exists" in err

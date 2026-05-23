"""Tests for Supabase-only QA store setup."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.qa_ai.store_setup import (
    is_seed_job_id,
    load_reference_data_only,
    normalize_case,
    validate_case,
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


def test_validate_case_accepts_valid_case():
    err = validate_case({
        "fingerprint": "geo_test",
        "test_jobs": [
            {"id": "job_001", "address": "100 Main, Kirkland QC", "service_type": "window_cleaning"}
        ],
    })
    assert err is None


def test_purge_supabase_seed_artifacts():
    mock_sb = AsyncMock()
    mock_sb.enabled = True
    mock_sb.delete_all = AsyncMock()
    mock_sb.delete_like = AsyncMock()

    with patch("app.qa_ai.store_setup.supabase", mock_sb):
        result = asyncio.run(__import__("app.qa_ai.store_setup", fromlist=["purge_supabase_seed_artifacts"]).purge_supabase_seed_artifacts())

    assert result["purged"] is True
    assert mock_sb.delete_all.call_count >= 6

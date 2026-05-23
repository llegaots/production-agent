"""Phase 6 orchestrator tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

pytestmark = pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") and not (ROOT / ".env").is_file(),
    reason="Supabase required",
)


@pytest.fixture
def anthropic_key():
    if os.getenv("ANTHROPIC_API_KEY"):
        return True
    from app.config import get_settings

    return bool(get_settings().anthropic_api_key)


def test_next_week_job_loading():
    from app.orchestrator.runner import _load_pending_job_ids, _next_week_bounds

    start, end = _next_week_bounds()
    jobs = _load_pending_job_ids(start, end, limit=5)
    assert isinstance(jobs, list)


def test_orchestrator_programmatic_without_anthropic():
    """Tool + critic loop without Anthropic (CI-friendly)."""
    from app.orchestrator import run_scheduling_mission
    from app.orchestrator.schemas import ScheduleWeekInput
    from app.tools._db import tools_db

    result = run_scheduling_mission(
        ScheduleWeekInput(
            user_request="Schedule next week's jobs.",
            use_llm_critic=False,
            use_agent=False,
            max_iterations=2,
        )
    )
    assert result.schedule_run_id
    assert result.iteration_count >= 1
    iters = (
        tools_db()
        .table("schedule_run_iterations")
        .select("iteration_number, approved")
        .eq("schedule_run_id", str(result.schedule_run_id))
        .execute()
        .data
    )
    assert len(iters) >= 1


@pytest.mark.anthropic
def test_orchestrator_end_to_end_with_anthropic(anthropic_key):
    """Full loop using Anthropic tool-use (requires API key)."""
    if not os.getenv("RUN_ANTHROPIC_E2E"):
        pytest.skip("Set RUN_ANTHROPIC_E2E=1 to run live Anthropic orchestrator test")
    if not anthropic_key:
        pytest.skip("ANTHROPIC_API_KEY required for orchestrator E2E")

    from anthropic import APIStatusError

    from app.orchestrator import run_scheduling_mission
    from app.orchestrator.schemas import ScheduleWeekInput
    from app.tools._db import tools_db

    try:
        result = run_scheduling_mission(
            ScheduleWeekInput(
                user_request="Schedule next week's jobs.",
                use_llm_critic=False,
                use_agent=True,
                max_iterations=2,
            )
        )
    except APIStatusError as exc:
        if exc.status_code == 429:
            pytest.skip(f"Anthropic rate limited: {exc}")
        raise

    assert result.schedule_run_id
    assert result.iteration_count >= 1
    assert result.week_start <= result.week_end

    run_row = (
        tools_db()
        .table("schedule_runs")
        .select("*")
        .eq("id", str(result.schedule_run_id))
        .single()
        .execute()
        .data
    )
    assert run_row["status"] in ("approved", "needs_human_review")

    iters = (
        tools_db()
        .table("schedule_run_iterations")
        .select("*")
        .eq("schedule_run_id", str(result.schedule_run_id))
        .execute()
        .data
    )
    assert len(iters) == result.iteration_count
    if result.langfuse_trace_id:
        assert len(result.langfuse_trace_id) > 0


def test_schedule_runs_persisted_on_human_review():
    from app.orchestrator import run_scheduling_mission
    from app.orchestrator.schemas import ScheduleWeekInput

    result = run_scheduling_mission(
        ScheduleWeekInput(
            user_request="Schedule next week's jobs quickly.",
            use_llm_critic=False,
            use_agent=False,
            max_iterations=1,
        )
    )
    if result.approved:
        pytest.skip("Need rejection path to test human review flag")
    assert result.needs_human_review is True
    assert result.status == "needs_human_review"

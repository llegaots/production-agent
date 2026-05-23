"""
Phase 6 orchestrator E2E tests.

Requires Supabase (service role). Seeds isolated rows via YAML fixtures under tests/scenarios/.
Programmatic orchestrator path (use_agent=False) is default for CI stability.
"""

from __future__ import annotations

import os

import pytest

from app.orchestrator.runner import run_scheduling_mission
from app.orchestrator.schemas import ScheduleWeekInput

from tests.e2e.assertions import assert_scenario_result, log_langfuse_on_failure
from tests.e2e.scenario_loader import OrchestratorScenario

pytestmark = [pytest.mark.e2e]

PROGRAMMATIC_SCENARIOS = [
    "simple_week",
    "tight_constraints",
    "equipment_scarce",
    "infeasible",
]

LLM_SCENARIOS = [
    "preference_heavy",
]


def _run_mission(scenario: OrchestratorScenario, *, use_agent: bool):
    return run_scheduling_mission(
        ScheduleWeekInput(
            user_request=scenario.user_request,
            week_start=scenario.week_start,
            week_end=scenario.week_end,
            max_iterations=scenario.max_iterations,
            use_llm_critic=scenario.use_llm_critic,
            use_agent=use_agent,
            job_id_prefix=scenario.id_prefix,
            job_load_limit=len(scenario.all_job_ids),
        )
    )


@pytest.mark.parametrize("orchestrator_scenario", PROGRAMMATIC_SCENARIOS, indirect=True)
def test_orchestrator_e2e_programmatic(orchestrator_scenario: OrchestratorScenario) -> None:
    """Deterministic tool loop — suitable for CI when Supabase credentials are set."""
    if orchestrator_scenario.requires_agent:
        pytest.skip("scenario requires Anthropic agent loop")

    result = _run_mission(orchestrator_scenario, use_agent=False)

    try:
        assert_scenario_result(result, orchestrator_scenario)
    except AssertionError:
        log_langfuse_on_failure(result, scenario=orchestrator_scenario.name)
        raise


@pytest.mark.llm
@pytest.mark.parametrize("orchestrator_scenario", LLM_SCENARIOS, indirect=True)
def test_orchestrator_e2e_llm(orchestrator_scenario: OrchestratorScenario) -> None:
    """Agent + critic iterations with real Anthropic calls."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    if os.environ.get("CI") == "true" and os.environ.get("RUN_LLM_E2E") != "1":
        pytest.skip("LLM E2E disabled in CI (set RUN_LLM_E2E=1 to enable)")

    result = _run_mission(orchestrator_scenario, use_agent=True)

    try:
        assert_scenario_result(result, orchestrator_scenario)
    except AssertionError:
        log_langfuse_on_failure(result, scenario=orchestrator_scenario.name)
        raise


@pytest.mark.llm
@pytest.mark.parametrize("orchestrator_scenario", ["simple_week"], indirect=True)
def test_orchestrator_e2e_agent_smoke(orchestrator_scenario: OrchestratorScenario) -> None:
    """Optional live agent smoke on the simplest fixture."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    if os.environ.get("CI") == "true" and os.environ.get("RUN_LLM_E2E") != "1":
        pytest.skip("LLM E2E disabled in CI (set RUN_LLM_E2E=1 to enable)")

    result = _run_mission(orchestrator_scenario, use_agent=True)

    try:
        assert result.iteration_count >= 1
        assert result.status in ("approved", "needs_human_review")
        log_langfuse_on_failure(result, scenario=orchestrator_scenario.name)
    except AssertionError:
        log_langfuse_on_failure(result, scenario=orchestrator_scenario.name)
        raise

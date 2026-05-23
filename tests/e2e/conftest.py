"""E2E fixtures: isolated Supabase seed per scenario."""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tests.e2e.scenario_loader import (  # noqa: E402
    OrchestratorScenario,
    cleanup_scenario_prefix,
    load_scenario,
)

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: orchestrator end-to-end tests (Supabase)")
    config.addinivalue_line("markers", "llm: tests that call Anthropic (skip in CI)")


@pytest.fixture(scope="session")
def e2e_run_prefix() -> str:
    return f"e2e-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def orchestrator_scenario(
    e2e_run_prefix: str,
    request: pytest.FixtureRequest,
) -> Generator[OrchestratorScenario, None, None]:
    scenario_name = request.param
    yaml_path = SCENARIOS_DIR / f"{scenario_name}.yaml"
    if not yaml_path.is_file():
        pytest.skip(f"missing scenario fixture: {yaml_path}")

    if not os.environ.get("SUPABASE_URL") and not (ROOT / ".env").is_file():
        pytest.skip("SUPABASE_URL (or backend .env) required for E2E")

    scenario = load_scenario(yaml_path, run_prefix=e2e_run_prefix)
    from tests.e2e.scenario_loader import seed_scenario_to_supabase

    seed_scenario_to_supabase(scenario)
    try:
        yield scenario
    finally:
        cleanup_scenario_prefix(scenario.id_prefix)

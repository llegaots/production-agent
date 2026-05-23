"""Shared optimizer fixtures (no DB, no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.optimizer.models import (  # noqa: E402
    OptimizerInput,
    ScheduleCrew,
    ScheduleJob,
    TimeWindow,
    TravelMatrix,
)

# Minutes from shift start: 9:00 = 540, 11:00 = 660, 14:00 = 840
NINE_AM = 540
ELEVEN_AM = 660
TWO_PM = 840


def _cluster_matrix(num_jobs: int, hub_travel: int = 5, job_travel: int = 8) -> list[list[int]]:
    """Depot at 0; jobs at 1..num_jobs in one geographic cluster."""
    n = num_jobs + 1
    matrix = [[0] * n for _ in range(n)]
    for i in range(1, n):
        matrix[0][i] = matrix[i][0] = hub_travel
    for i in range(1, n):
        for j in range(i + 1, n):
            matrix[i][j] = matrix[j][i] = job_travel
    return matrix


@pytest.fixture
def cluster_five_jobs_one_crew() -> OptimizerInput:
    """Five jobs in one cluster, single crew, fits in one shift."""
    matrix = _cluster_matrix(5)
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="solo",
                depot_index=0,
                skills=["residential", "commercial"],
                equipment_kinds=["ladder_28", "van"],
                shift_start_minute=0,
                shift_end_minute=480,
            ),
        ],
        jobs=[
            ScheduleJob(
                id=f"j{i}",
                node_index=i,
                service_minutes=45,
                time_window=TimeWindow(earliest_minute=0, latest_minute=450),
                mandatory=True,
            )
            for i in range(1, 6)
        ],
        travel=TravelMatrix(minutes=matrix),
        time_limit_seconds=1,
    )


@pytest.fixture
def high_rise_three_jobs_two_crews() -> OptimizerInput:
    """Three high-rise jobs; only bravo is certified."""
    matrix = _cluster_matrix(3, hub_travel=10, job_travel=12)
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="alpha",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["ladder_28", "van"],
            ),
            ScheduleCrew(
                id="bravo",
                depot_index=0,
                skills=["high_rise", "rope_access"],
                equipment_kinds=["rope_kit", "van"],
            ),
        ],
        jobs=[
            ScheduleJob(
                id=f"hr{i}",
                node_index=i,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=0, latest_minute=420),
                required_skills=["high_rise"],
                mandatory=True,
            )
            for i in range(1, 4)
        ],
        travel=TravelMatrix(minutes=matrix),
        time_limit_seconds=1,
    )


@pytest.fixture
def morning_window_job_input() -> OptimizerInput:
    """Job must be served 9–11am; wide day window decoy should not land at 2pm."""
    matrix = [
        [0, 20],
        [20, 0],
    ]
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="solo",
                depot_index=0,
                skills=[],
                equipment_kinds=[],
                shift_start_minute=0,
                shift_end_minute=720,
            ),
        ],
        jobs=[
            ScheduleJob(
                id="morning-only",
                node_index=1,
                service_minutes=30,
                time_window=TimeWindow(earliest_minute=NINE_AM, latest_minute=ELEVEN_AM),
                mandatory=True,
            ),
        ],
        travel=TravelMatrix(minutes=matrix),
        horizon_minutes=900,
        time_limit_seconds=1,
    )


@pytest.fixture
def water_fed_pole_equipment_input() -> OptimizerInput:
    """WFP job only assignable to crew carrying water_fed_pole."""
    matrix = [
        [0, 15, 15],
        [15, 0, 20],
        [15, 20, 0],
    ]
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="alpha",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["ladder_28", "van"],
            ),
            ScheduleCrew(
                id="bravo",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["water_fed_pole", "van"],
            ),
        ],
        jobs=[
            ScheduleJob(
                id="wfp-job",
                node_index=1,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                required_equipment=["water_fed_pole"],
                mandatory=True,
            ),
            ScheduleJob(
                id="filler",
                node_index=2,
                service_minutes=30,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                mandatory=False,
            ),
        ],
        travel=TravelMatrix(minutes=matrix),
        time_limit_seconds=1,
    )


@pytest.fixture
def overload_fifty_jobs_one_crew() -> OptimizerInput:
    """Fifty mandatory jobs cannot fit in a single 8h shift (capacity infeasible)."""
    n = 51
    matrix = [[5 if i != j else 0 for j in range(n)] for i in range(n)]
    # Cap crew at 6 stops so OR-Tools fails fast without a long search.
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="solo",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["van"],
                shift_start_minute=0,
                shift_end_minute=480,
                max_jobs=6,
            ),
        ],
        jobs=[
            ScheduleJob(
                id=f"bulk-{i:02d}",
                node_index=i,
                service_minutes=20,
                time_window=TimeWindow(earliest_minute=0, latest_minute=480),
                mandatory=True,
            )
            for i in range(1, 51)
        ],
        travel=TravelMatrix(minutes=matrix),
        time_limit_seconds=1,
    )


@pytest.fixture
def forced_preference_violation_input() -> OptimizerInput:
    """j-pref prefers alpha but only bravo can serve it (high_rise)."""
    matrix = _cluster_matrix(2, hub_travel=8, job_travel=10)
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="alpha",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["ladder_28"],
            ),
            ScheduleCrew(
                id="bravo",
                depot_index=0,
                skills=["high_rise", "residential"],
                equipment_kinds=["rope_kit"],
            ),
        ],
        jobs=[
            ScheduleJob(
                id="j-pref",
                node_index=1,
                service_minutes=50,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                required_skills=["high_rise"],
                preferred_crew_id="alpha",
                preference_penalty=50,
                mandatory=True,
            ),
            ScheduleJob(
                id="j-other",
                node_index=2,
                service_minutes=40,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                required_skills=["residential"],
                mandatory=True,
            ),
        ],
        travel=TravelMatrix(minutes=matrix),
        time_limit_seconds=1,
    )

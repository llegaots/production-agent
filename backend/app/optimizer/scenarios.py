"""Hardcoded scenarios for tests and manual demos (no database)."""

from __future__ import annotations

from app.optimizer.models import (
    OptimizerInput,
    ScheduleCrew,
    ScheduleJob,
    TimeWindow,
    TravelMatrix,
)

# 3 nodes: depot0, depot1 (same location), job sites at indices 2,3,4
# Matrix: symmetric travel minutes
_MATRIX_5 = [
    [0, 0, 15, 25, 20],
    [0, 0, 15, 25, 20],
    [15, 15, 0, 12, 18],
    [25, 25, 12, 0, 10],
    [20, 20, 18, 10, 0],
]


def feasible_two_crew_scenario() -> OptimizerInput:
    """Two crews, four jobs — should produce a valid schedule."""
    return OptimizerInput(
        crews=[
            ScheduleCrew(
                id="alpha",
                depot_index=0,
                skills=["residential", "commercial"],
                equipment_kinds=["ladder_28", "van"],
                shift_start_minute=0,
                shift_end_minute=480,
            ),
            ScheduleCrew(
                id="bravo",
                depot_index=1,
                skills=["high_rise", "rope_access"],
                equipment_kinds=["rope_kit", "van"],
                shift_start_minute=0,
                shift_end_minute=480,
            ),
        ],
        jobs=[
            ScheduleJob(
                id="j1",
                node_index=2,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=240),
                required_skills=["residential"],
                required_equipment=["ladder_28"],
                preferred_crew_id="alpha",
            ),
            ScheduleJob(
                id="j2",
                node_index=3,
                service_minutes=45,
                time_window=TimeWindow(earliest_minute=90, latest_minute=300),
                required_skills=["commercial"],
            ),
            ScheduleJob(
                id="j3",
                node_index=4,
                service_minutes=90,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                required_skills=["high_rise"],
                required_equipment=["rope_kit"],
                preferred_crew_id="bravo",
            ),
        ],
        travel=TravelMatrix(minutes=_MATRIX_5),
        time_limit_seconds=5,
    )


def infeasible_skills_scenario() -> OptimizerInput:
    """Job requires a skill no crew has."""
    base = feasible_two_crew_scenario()
    return base.model_copy(
        update={
            "jobs": base.jobs
            + [
                ScheduleJob(
                    id="impossible",
                    node_index=3,
                    service_minutes=30,
                    time_window=TimeWindow(earliest_minute=0, latest_minute=480),
                    required_skills=["underwater_glass"],
                    mandatory=True,
                )
            ]
        }
    )


def infeasible_time_window_scenario() -> OptimizerInput:
    """Arrival window is too tight for travel + service."""
    return OptimizerInput(
        crews=[
            ScheduleCrew(id="solo", depot_index=0, skills=[], equipment_kinds=[]),
        ],
        jobs=[
            ScheduleJob(
                id="j-far",
                node_index=4,
                service_minutes=120,
                time_window=TimeWindow(earliest_minute=0, latest_minute=5),
            ),
            ScheduleJob(
                id="j-far-2",
                node_index=3,
                service_minutes=120,
                time_window=TimeWindow(earliest_minute=0, latest_minute=5),
            ),
        ],
        travel=TravelMatrix(minutes=_MATRIX_5),
        time_limit_seconds=3,
    )


def infeasible_equipment_scenario() -> OptimizerInput:
    base = feasible_two_crew_scenario()
    return base.model_copy(
        update={
            "jobs": [
                ScheduleJob(
                    id="needs-lift",
                    node_index=3,
                    service_minutes=60,
                    time_window=TimeWindow(earliest_minute=0, latest_minute=480),
                    required_equipment=["scissor_lift"],
                    mandatory=True,
                )
            ]
        }
    )

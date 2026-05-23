"""Phase 3 optimizer tests (no database)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.optimizer import InfeasibleScheduleError, solve
from app.optimizer.models import OptimizerInput, ScheduleCrew, ScheduleJob, TimeWindow, TravelMatrix
from app.optimizer.scenarios import (
    feasible_two_crew_scenario,
    infeasible_equipment_scenario,
    infeasible_skills_scenario,
    infeasible_time_window_scenario,
)


def _assigned_ids(result) -> set[str]:
    return set(result.assigned_job_ids)


def test_feasible_scenario_produces_valid_routes():
    inp = feasible_two_crew_scenario()
    result = solve(inp)

    assert result.status in ("optimal", "feasible")
    mandatory = {j.id for j in inp.jobs if j.mandatory}
    assert mandatory.issubset(_assigned_ids(result))

    for route in result.routes:
        assert route.end_minute <= 480
        prev_depart = 0
        for stop in route.stops:
            assert stop.arrival_minute >= stop.start_minute
            assert stop.depart_minute == stop.start_minute + next(
                j.service_minutes for j in inp.jobs if j.id == stop.job_id
            )
            job = next(j for j in inp.jobs if j.id == stop.job_id)
            assert stop.arrival_minute >= job.time_window.earliest_minute
            assert stop.arrival_minute <= job.time_window.latest_minute
            assert stop.arrival_minute >= prev_depart or prev_depart == 0
            prev_depart = stop.depart_minute

    crew_ids = {r.crew_id for r in result.routes if r.stops}
    assert "alpha" in crew_ids or "bravo" in crew_ids


def test_high_rise_job_goes_to_bravo():
    inp = feasible_two_crew_scenario()
    result = solve(inp)
    bravo = next(r for r in result.routes if r.crew_id == "bravo")
    assert any(s.job_id == "j3" for s in bravo.stops)


def test_infeasible_skills_fails_cleanly():
    inp = infeasible_skills_scenario()
    result = solve(inp)
    assert result.status == "infeasible"
    assert "impossible" in result.unassigned_job_ids
    assert any("impossible" in m or "underwater" in m for m in result.messages)

    with pytest.raises(InfeasibleScheduleError) as exc:
        solve(inp, strict=True)
    assert "impossible" in exc.value.unassigned_job_ids


def test_infeasible_equipment_fails_cleanly():
    inp = infeasible_equipment_scenario()
    result = solve(inp)
    assert result.status == "infeasible"
    assert "needs-lift" in result.unassigned_job_ids

    with pytest.raises(InfeasibleScheduleError):
        solve(inp, strict=True)


def test_infeasible_time_windows():
    inp = infeasible_time_window_scenario()
    result = solve(inp)
    assert result.status == "infeasible"
    assert result.unassigned_job_ids

    with pytest.raises(InfeasibleScheduleError):
        solve(inp, strict=True)


def test_soft_preference_does_not_block_assignment():
    """Non-preferred crew is allowed; j1 should still be scheduled."""
    inp = feasible_two_crew_scenario()
    result = solve(inp)
    assert "j1" in _assigned_ids(result)


def test_max_jobs_per_crew():
    """Each crew may visit at most one job; two jobs must split across crews."""
    matrix = [
        [0, 10, 10],
        [10, 0, 10],
        [10, 10, 0],
    ]
    inp = OptimizerInput(
        crews=[
            ScheduleCrew(id="c1", depot_index=0, max_jobs=1),
            ScheduleCrew(id="c2", depot_index=0, max_jobs=1),
        ],
        jobs=[
            ScheduleJob(
                id="a",
                node_index=1,
                service_minutes=30,
                time_window=TimeWindow(earliest_minute=0, latest_minute=400),
                mandatory=True,
            ),
            ScheduleJob(
                id="b",
                node_index=2,
                service_minutes=30,
                time_window=TimeWindow(earliest_minute=0, latest_minute=400),
                mandatory=True,
            ),
        ],
        travel=TravelMatrix(minutes=matrix),
        time_limit_seconds=5,
    )
    result = solve(inp)
    assert result.status in ("optimal", "feasible")
    assert _assigned_ids(result) == {"a", "b"}

"""Phase 3 OR-Tools optimizer tests (no database, no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.optimizer import InfeasibleScheduleError, solve  # noqa: E402

NINE_AM = 540
ELEVEN_AM = 660
TWO_PM = 840


def _route_for_crew(result, crew_id: str):
    return next((r for r in result.routes if r.crew_id == crew_id), None)


def _stop(result, job_id: str):
    for route in result.routes:
        for stop in route.stops:
            if stop.job_id == job_id:
                return stop, route.crew_id
    return None, None


# --- Happy path ---


def test_happy_path_five_jobs_one_cluster_one_crew(cluster_five_jobs_one_crew):
    result = solve(cluster_five_jobs_one_crew)

    assert result.status in ("optimal", "feasible")
    assert len(result.assigned_job_ids) == 5
    assert result.unassigned_job_ids == []

    route = _route_for_crew(result, "solo")
    assert route is not None
    assert len(route.stops) == 5
    assert route.end_minute <= 480


# --- Skill matching ---


def test_high_rise_jobs_only_on_certified_crew(high_rise_three_jobs_two_crews):
    result = solve(high_rise_three_jobs_two_crews)

    assert result.status in ("optimal", "feasible")
    assert set(result.assigned_job_ids) == {"hr1", "hr2", "hr3"}

    alpha = _route_for_crew(result, "alpha")
    bravo = _route_for_crew(result, "bravo")
    assert alpha is None or len(alpha.stops) == 0
    assert bravo is not None
    assert len(bravo.stops) == 3
    assert {s.job_id for s in bravo.stops} == {"hr1", "hr2", "hr3"}


# --- Time windows ---


def test_morning_window_not_scheduled_at_afternoon(morning_window_job_input):
    result = solve(morning_window_job_input)

    assert result.status in ("optimal", "feasible")
    stop, _ = _stop(result, "morning-only")
    assert stop is not None
    assert NINE_AM <= stop.arrival_minute <= ELEVEN_AM
    assert stop.arrival_minute < TWO_PM


# --- Equipment ---


def test_water_fed_pole_only_on_equipped_crew(water_fed_pole_equipment_input):
    result = solve(water_fed_pole_equipment_input)

    assert result.status in ("optimal", "feasible")
    _, crew_id = _stop(result, "wfp-job")
    assert crew_id == "bravo"

    alpha = _route_for_crew(result, "alpha")
    if alpha:
        assert "wfp-job" not in {s.job_id for s in alpha.stops}


# --- Infeasibility ---


def test_fifty_jobs_one_crew_fails_cleanly(overload_fifty_jobs_one_crew):
    result = solve(overload_fifty_jobs_one_crew)

    assert result.status == "infeasible"
    assert len(result.unassigned_job_ids) >= 44
    assert result.messages
    assert any(
        "Mandatory" in m
        or "feasible" in m.lower()
        or "not scheduled" in m.lower()
        or "could not find" in m.lower()
        for m in result.messages
    )

    with pytest.raises(InfeasibleScheduleError) as exc:
        solve(overload_fifty_jobs_one_crew, strict=True)
    assert exc.value.unassigned_job_ids
    assert str(exc.value)


# --- Soft preference ---


def test_preference_violation_flagged_when_forced(forced_preference_violation_input):
    result = solve(forced_preference_violation_input)

    assert result.status in ("optimal", "feasible")
    assert "j-pref" in result.assigned_job_ids
    _, crew_id = _stop(result, "j-pref")
    assert crew_id == "bravo"

    assert any("Preference violation" in m and "j-pref" in m for m in result.messages)
    assert any("alpha" in m for m in result.messages)

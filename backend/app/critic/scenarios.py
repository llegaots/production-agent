"""Good vs bad schedules for critic tests (no database)."""

from __future__ import annotations

from datetime import date

from app.critic.schemas import JobCoordinate, ReviewScheduleInput
from app.optimizer import solve
from app.optimizer.models import (
    CrewRoute,
    OptimizerInput,
    OptimizerResult,
    RouteStop,
    ScheduleCrew,
    ScheduleJob,
    TimeWindow,
    TravelMatrix,
)
from app.optimizer.scenarios import feasible_two_crew_scenario

_MATRIX = feasible_two_crew_scenario().travel.minutes


def good_review_input(target: date | None = None) -> ReviewScheduleInput:
    """Feasible optimizer result with preferences honored."""
    opt_in = feasible_two_crew_scenario()
    result = solve(opt_in)
    coords = [
        JobCoordinate(job_id="j1", lat=45.51, lng=-73.57),
        JobCoordinate(job_id="j2", lat=45.52, lng=-73.56),
        JobCoordinate(job_id="j3", lat=45.53, lng=-73.55),
    ]
    return ReviewScheduleInput(
        target_date=target or date.today(),
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=coords,
        persist=False,
        use_llm=False,
    )


def bad_review_input_preference_violations(target: date | None = None) -> ReviewScheduleInput:
    """j3 (high-rise) assigned to alpha instead of bravo."""
    good = good_review_input(target)
    bad_routes = [
        CrewRoute(
            crew_id="alpha",
            stops=[
                RouteStop(
                    job_id="j1",
                    node_index=2,
                    arrival_minute=60,
                    start_minute=60,
                    depart_minute=120,
                ),
                RouteStop(
                    job_id="j3",
                    node_index=4,
                    arrival_minute=130,
                    start_minute=130,
                    depart_minute=220,
                ),
            ],
            total_travel_minutes=40,
            total_service_minutes=150,
            end_minute=230,
        ),
        CrewRoute(
            crew_id="bravo",
            stops=[
                RouteStop(
                    job_id="j2",
                    node_index=3,
                    arrival_minute=90,
                    start_minute=90,
                    depart_minute=135,
                ),
            ],
            total_travel_minutes=25,
            total_service_minutes=45,
            end_minute=150,
        ),
    ]
    result = OptimizerResult(
        status="feasible",
        routes=bad_routes,
        unassigned_job_ids=[],
    )
    return good.model_copy(update={"optimizer_result": result, "use_llm": False})


def bad_review_input_geographic_spray(target: date | None = None) -> ReviewScheduleInput:
    """Single crew with jobs spread across far-apart coordinates."""
    opt_in = OptimizerInput(
        crews=[
            ScheduleCrew(
                id="solo",
                depot_index=0,
                skills=["residential", "commercial", "high_rise"],
                equipment_kinds=["ladder_28", "rope_kit", "van"],
            ),
        ],
        jobs=[
            ScheduleJob(
                id="far-a",
                node_index=2,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                preferred_crew_id="solo",
            ),
            ScheduleJob(
                id="far-b",
                node_index=3,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                preferred_crew_id="solo",
            ),
            ScheduleJob(
                id="far-c",
                node_index=4,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                preferred_crew_id="solo",
            ),
        ],
        travel=TravelMatrix(minutes=_MATRIX),
        time_limit_seconds=5,
    )
    result = OptimizerResult(
        status="feasible",
        routes=[
            CrewRoute(
                crew_id="solo",
                stops=[
                    RouteStop(
                        job_id="far-a",
                        node_index=2,
                        arrival_minute=60,
                        start_minute=60,
                        depart_minute=120,
                    ),
                    RouteStop(
                        job_id="far-b",
                        node_index=3,
                        arrival_minute=200,
                        start_minute=200,
                        depart_minute=260,
                    ),
                    RouteStop(
                        job_id="far-c",
                        node_index=4,
                        arrival_minute=350,
                        start_minute=350,
                        depart_minute=410,
                    ),
                ],
                total_travel_minutes=180,
                total_service_minutes=180,
                end_minute=420,
            )
        ],
    )
    coords = [
        JobCoordinate(job_id="far-a", lat=45.40, lng=-73.80),
        JobCoordinate(job_id="far-b", lat=45.55, lng=-73.40),
        JobCoordinate(job_id="far-c", lat=45.62, lng=-73.70),
    ]
    return ReviewScheduleInput(
        target_date=target or date.today(),
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=coords,
        persist=False,
        use_llm=False,
    )


def bad_review_input_equipment_mismatch(target: date | None = None) -> ReviewScheduleInput:
    """Crew without rope_kit assigned high-rise job."""
    opt_in = feasible_two_crew_scenario()
    result = OptimizerResult(
        status="feasible",
        routes=[
            CrewRoute(
                crew_id="alpha",
                stops=[
                    RouteStop(
                        job_id="j1",
                        node_index=2,
                        arrival_minute=60,
                        start_minute=60,
                        depart_minute=120,
                    ),
                    RouteStop(
                        job_id="j3",
                        node_index=4,
                        arrival_minute=130,
                        start_minute=130,
                        depart_minute=220,
                    ),
                ],
                total_travel_minutes=35,
                total_service_minutes=150,
                end_minute=230,
            ),
        ],
        unassigned_job_ids=["j2"],
    )
    # alpha lacks rope_kit in feasible scenario
    return ReviewScheduleInput(
        target_date=target or date.today(),
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=[
            JobCoordinate(job_id="j1", lat=45.51, lng=-73.57),
            JobCoordinate(job_id="j2", lat=45.52, lng=-73.56),
            JobCoordinate(job_id="j3", lat=45.53, lng=-73.55),
        ],
        persist=False,
        use_llm=False,
    )

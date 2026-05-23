"""Good vs bad schedules for critic tests (no database)."""

from __future__ import annotations

from datetime import date, timedelta

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

# Morning preference: 8:00–11:00 from shift start at midnight+480
MORNING_WINDOW = TimeWindow(earliest_minute=480, latest_minute=660)
AFTERNOON_ARRIVAL = 840  # 2:00 PM


def _week_friday(target: date) -> date:
    monday = target - timedelta(days=target.weekday())
    return monday + timedelta(days=4)


def good_review_input(target: date | None = None) -> ReviewScheduleInput:
    """Feasible optimizer result with preferences honored."""
    target = target or date.today()
    opt_in = feasible_two_crew_scenario()
    result = solve(opt_in)
    coords = [
        JobCoordinate(job_id="j1", lat=45.51, lng=-73.57),
        JobCoordinate(job_id="j2", lat=45.52, lng=-73.56),
        JobCoordinate(job_id="j3", lat=45.53, lng=-73.55),
    ]
    monday = target - timedelta(days=target.weekday())
    return ReviewScheduleInput(
        target_date=target,
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=coords,
        job_planned_day={
            "j1": monday,
            "j2": monday + timedelta(days=1),
            "j3": monday + timedelta(days=2),
        },
        persist=False,
        use_llm=False,
    )


def bad_geographic_zigzag(target: date | None = None) -> ReviewScheduleInput:
    """One crew bouncing between distant neighborhoods."""
    return bad_review_input_geographic_spray(target)


def bad_review_input_geographic_spray(target: date | None = None) -> ReviewScheduleInput:
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
            ),
            ScheduleJob(
                id="far-b",
                node_index=3,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
            ),
            ScheduleJob(
                id="far-c",
                node_index=4,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
            ),
        ],
        travel=TravelMatrix(minutes=_MATRIX),
        time_limit_seconds=1,
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


def bad_week_fill_friday_stack(target: date | None = None) -> ReviewScheduleInput:
    """Empty Mon/Tue; all jobs jammed into Friday."""
    target = target or date.today()
    friday = _week_friday(target)
    opt_in = OptimizerInput(
        crews=[ScheduleCrew(id="solo", depot_index=0, skills=["residential"], equipment_kinds=["van"])],
        jobs=[
            ScheduleJob(
                id=f"j{i}",
                node_index=i,
                service_minutes=45,
                time_window=TimeWindow(earliest_minute=0, latest_minute=480),
                mandatory=True,
            )
            for i in range(1, 6)
        ],
        travel=TravelMatrix(
            minutes=[[0 if i == j else 8 for j in range(6)] for i in range(6)]
        ),
        time_limit_seconds=1,
    )
    result = OptimizerResult(
        status="feasible",
        routes=[
            CrewRoute(
                crew_id="solo",
                stops=[
                    RouteStop(
                        job_id=f"j{i}",
                        node_index=i,
                        arrival_minute=60 + i * 50,
                        start_minute=60 + i * 50,
                        depart_minute=105 + i * 50,
                    )
                    for i in range(1, 6)
                ],
                total_travel_minutes=40,
                total_service_minutes=225,
                end_minute=400,
            )
        ],
    )
    return ReviewScheduleInput(
        target_date=target,
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=[JobCoordinate(job_id=f"j{i}", lat=45.51, lng=-73.57) for i in range(1, 6)],
        job_planned_day={f"j{i}": friday for i in range(1, 6)},
        persist=False,
        use_llm=False,
    )


def bad_morning_preference_afternoon(target: date | None = None) -> ReviewScheduleInput:
    """Customer morning window; stop scheduled at 2pm."""
    opt_in = OptimizerInput(
        crews=[ScheduleCrew(id="solo", depot_index=0, skills=["residential"], equipment_kinds=["van"])],
        jobs=[
            ScheduleJob(
                id="morning-client",
                node_index=1,
                service_minutes=60,
                time_window=MORNING_WINDOW,
                preferred_crew_id="solo",
            ),
        ],
        travel=TravelMatrix(minutes=[[0, 15], [15, 0]]),
        time_limit_seconds=1,
    )
    result = OptimizerResult(
        status="feasible",
        routes=[
            CrewRoute(
                crew_id="solo",
                stops=[
                    RouteStop(
                        job_id="morning-client",
                        node_index=1,
                        arrival_minute=AFTERNOON_ARRIVAL,
                        start_minute=AFTERNOON_ARRIVAL,
                        depart_minute=AFTERNOON_ARRIVAL + 60,
                    )
                ],
                total_travel_minutes=15,
                total_service_minutes=60,
                end_minute=AFTERNOON_ARRIVAL + 60,
            )
        ],
    )
    return ReviewScheduleInput(
        target_date=target or date.today(),
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=[JobCoordinate(job_id="morning-client", lat=45.51, lng=-73.57)],
        persist=False,
        use_llm=False,
    )


def bad_equipment_ground_floor_ladder(target: date | None = None) -> ReviewScheduleInput:
    """Ground-floor job incorrectly requires ladder equipment."""
    opt_in = OptimizerInput(
        crews=[
            ScheduleCrew(
                id="alpha",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["ladder_28", "van"],
            ),
        ],
        jobs=[
            ScheduleJob(
                id="ground-1",
                node_index=1,
                service_minutes=45,
                time_window=TimeWindow(earliest_minute=60, latest_minute=400),
                required_equipment=["ladder_28"],
            ),
        ],
        travel=TravelMatrix(minutes=[[0, 10], [10, 0]]),
        time_limit_seconds=1,
    )
    result = OptimizerResult(
        status="feasible",
        routes=[
            CrewRoute(
                crew_id="alpha",
                stops=[
                    RouteStop(
                        job_id="ground-1",
                        node_index=1,
                        arrival_minute=90,
                        start_minute=90,
                        depart_minute=135,
                    )
                ],
                total_travel_minutes=10,
                total_service_minutes=45,
                end_minute=145,
            )
        ],
    )
    return ReviewScheduleInput(
        target_date=target or date.today(),
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=[JobCoordinate(job_id="ground-1", lat=45.51, lng=-73.57)],
        job_tags={"ground-1": ["ground_floor"]},
        persist=False,
        use_llm=False,
    )


def bad_drive_time_blowout(target: date | None = None) -> ReviewScheduleInput:
    """4 hours driving for 3 hours of work on one crew-day."""
    opt_in = OptimizerInput(
        crews=[
            ScheduleCrew(
                id="solo",
                depot_index=0,
                skills=["residential"],
                equipment_kinds=["van"],
                shift_start_minute=0,
                shift_end_minute=480,
            ),
        ],
        jobs=[
            ScheduleJob(
                id=f"j{i}",
                node_index=i,
                service_minutes=60,
                time_window=TimeWindow(earliest_minute=0, latest_minute=450),
            )
            for i in range(1, 4)
        ],
        travel=TravelMatrix(minutes=[[0, 20, 20, 20], [20, 0, 20, 20], [20, 20, 0, 20], [20, 20, 20, 0]]),
        time_limit_seconds=1,
    )
    result = OptimizerResult(
        status="feasible",
        routes=[
            CrewRoute(
                crew_id="solo",
                stops=[
                    RouteStop(
                        job_id="j1",
                        node_index=1,
                        arrival_minute=60,
                        start_minute=60,
                        depart_minute=120,
                    ),
                    RouteStop(
                        job_id="j2",
                        node_index=2,
                        arrival_minute=200,
                        start_minute=200,
                        depart_minute=260,
                    ),
                    RouteStop(
                        job_id="j3",
                        node_index=3,
                        arrival_minute=340,
                        start_minute=340,
                        depart_minute=400,
                    ),
                ],
                total_travel_minutes=240,
                total_service_minutes=180,
                end_minute=440,
            )
        ],
    )
    return ReviewScheduleInput(
        target_date=target or date.today(),
        optimizer_input=opt_in,
        optimizer_result=result,
        job_coordinates=[JobCoordinate(job_id=f"j{i}", lat=45.51, lng=-73.57) for i in range(1, 4)],
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
                )
            ],
            total_travel_minutes=25,
            total_service_minutes=45,
            end_minute=150,
        ),
    ]
    result = OptimizerResult(status="feasible", routes=bad_routes, unassigned_job_ids=[])
    return good.model_copy(update={"optimizer_result": result, "use_llm": False})


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

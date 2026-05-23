"""Google OR-Tools VRP solver with hard and soft constraints."""

from __future__ import annotations

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.optimizer.exceptions import InfeasibleScheduleError
from app.optimizer.models import (
    CrewRoute,
    OptimizerInput,
    OptimizerResult,
    OptimizerStatus,
    RouteStop,
    ScheduleCrew,
    ScheduleJob,
)


def _crew_can_serve(crew: ScheduleCrew, job: ScheduleJob) -> bool:
    if job.required_skills and not set(job.required_skills).issubset(crew.skills):
        return False
    if job.required_equipment and not set(job.required_equipment).issubset(
        crew.equipment_kinds
    ):
        return False
    return True


def _feasible_crews(crews: list[ScheduleCrew], job: ScheduleJob) -> list[int]:
    return [i for i, crew in enumerate(crews) if _crew_can_serve(crew, job)]


def _restrict_vehicles_for_index(
    routing: pywrapcp.RoutingModel,
    routing_index: int,
    allowed_vehicle_ids: list[int],
    num_vehicles: int,
) -> None:
    """Restrict which vehicle may visit a node (OR-Tools VehicleVar)."""
    solver = routing.solver()
    vehicle_var = routing.VehicleVar(routing_index)
    allowed = set(allowed_vehicle_ids)
    for vehicle_id in range(num_vehicles):
        if vehicle_id not in allowed:
            solver.Add(vehicle_var != vehicle_id)


def _prevalidate(input_data: OptimizerInput) -> tuple[list[str], list[str]]:
    """Return (messages, mandatory_unassignable job ids)."""
    messages: list[str] = []
    blocked: list[str] = []
    for job in input_data.jobs:
        if not _feasible_crews(input_data.crews, job):
            msg = (
                f"Job {job.id} has no crew with required skills/equipment "
                f"(skills={job.required_skills}, equipment={job.required_equipment})"
            )
            messages.append(msg)
            if job.mandatory:
                blocked.append(job.id)
    return messages, blocked


def solve(input_data: OptimizerInput, *, strict: bool = False) -> OptimizerResult:
    """
    Assign jobs to crews and sequence stops per crew.

    Hard constraints: travel times, time windows, shift bounds, skills, equipment.
    Soft constraints: preferred crew (arc cost penalty).

    If ``strict`` is True and the problem is infeasible, raises InfeasibleScheduleError.
    """
    pre_messages, blocked = _prevalidate(input_data)
    crews = input_data.crews
    jobs = [j for j in input_data.jobs if j.id not in blocked]
    if not jobs:
        messages = pre_messages + ["No jobs remain after skill/equipment filtering"]
        return OptimizerResult(
            status="infeasible",
            unassigned_job_ids=blocked + [j.id for j in input_data.jobs],
            messages=messages,
        )
    matrix = input_data.travel.minutes
    num_vehicles = len(crews)
    starts = [c.depot_index for c in crews]
    ends = starts[:]

    job_by_node: dict[int, ScheduleJob] = {j.node_index: j for j in jobs}
    service_minutes = [0] * input_data.travel.size
    for job in jobs:
        service_minutes[job.node_index] = job.service_minutes

    manager = pywrapcp.RoutingIndexManager(input_data.travel.size, num_vehicles, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = matrix[from_node][to_node]
        service = service_minutes[from_node]
        return service + travel

    time_cb_index = routing.RegisterTransitCallback(time_callback)

    def make_cost_callback(vehicle_id: int):
        def cost_callback(from_index: int, to_index: int) -> int:
            cost = time_callback(from_index, to_index)
            to_node = manager.IndexToNode(to_index)
            job = job_by_node.get(to_node)
            if job and job.preferred_crew_id and crews[vehicle_id].id != job.preferred_crew_id:
                cost += job.preference_penalty
            return cost

        return cost_callback

    for vehicle_id in range(num_vehicles):
        routing.SetArcCostEvaluatorOfVehicle(
            routing.RegisterTransitCallback(make_cost_callback(vehicle_id)),
            vehicle_id,
        )

    routing.AddDimension(
        time_cb_index,
        120,
        input_data.horizon_minutes,
        False,
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    for job in jobs:
        index = manager.NodeToIndex(job.node_index)
        feasible = _feasible_crews(crews, job)
        _restrict_vehicles_for_index(routing, index, feasible, num_vehicles)
        time_dimension.CumulVar(index).SetRange(
            job.time_window.earliest_minute,
            job.time_window.latest_minute,
        )
        if not job.mandatory:
            routing.AddDisjunction([index], input_data.unassigned_penalty)

    for vehicle_id, crew in enumerate(crews):
        start_index = routing.Start(vehicle_id)
        end_index = routing.End(vehicle_id)
        time_dimension.CumulVar(start_index).SetRange(
            crew.shift_start_minute,
            crew.shift_end_minute,
        )
        time_dimension.CumulVar(end_index).SetRange(
            crew.shift_start_minute,
            crew.shift_end_minute,
        )
    if any(c.max_jobs is not None for c in crews):
        def demand_callback(from_index: int) -> int:
            node = manager.IndexToNode(from_index)
            return 1 if node in job_by_node else 0

        demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
        capacities = [c.max_jobs if c.max_jobs is not None else len(jobs) + 1 for c in crews]
        routing.AddDimensionWithVehicleCapacity(
            demand_cb,
            0,
            capacities,
            True,
            "JobsCount",
        )

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    if input_data.time_limit_seconds <= 1:
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.AUTOMATIC
        )
    else:
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
    params.time_limit.seconds = max(1, input_data.time_limit_seconds)

    solution = routing.SolveWithParameters(params)
    if solution is None:
        unassigned = [j.id for j in jobs if j.mandatory]
        messages = pre_messages + ["OR-Tools could not find a feasible routing solution"]
        result = OptimizerResult(
            status="infeasible",
            unassigned_job_ids=unassigned,
            messages=messages,
        )
        if strict:
            raise InfeasibleScheduleError(messages, unassigned)
        return result

    status: OptimizerStatus = (
        "optimal"
        if routing.status() == routing_enums_pb2.RoutingSearchStatus.ROUTING_OPTIMAL
        else "feasible"
    )

    routes: list[CrewRoute] = []
    assigned: set[str] = set()
    preference_violations: list[str] = []
    total_objective = solution.ObjectiveValue()

    for vehicle_id, crew in enumerate(crews):
        stops: list[RouteStop] = []
        travel_total = 0
        service_total = 0
        index = routing.Start(vehicle_id)
        prev_node = manager.IndexToNode(index)
        while not routing.IsEnd(index):
            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            travel_total += matrix[prev_node][next_node]
            if next_node in job_by_node:
                job = job_by_node[next_node]
                arrival = solution.Value(time_dimension.CumulVar(next_index))
                start = arrival
                depart = arrival + job.service_minutes
                if job.preferred_crew_id and job.preferred_crew_id != crew.id:
                    preference_violations.append(
                        f"Preference violation: job {job.id} prefers crew "
                        f"{job.preferred_crew_id} but assigned to {crew.id}"
                    )
                stops.append(
                    RouteStop(
                        job_id=job.id,
                        node_index=next_node,
                        arrival_minute=arrival,
                        start_minute=start,
                        depart_minute=depart,
                    )
                )
                service_total += job.service_minutes
                assigned.add(job.id)
            index = next_index
            prev_node = next_node

        end_minute = solution.Value(time_dimension.CumulVar(routing.End(vehicle_id)))
        routes.append(
            CrewRoute(
                crew_id=crew.id,
                stops=stops,
                total_travel_minutes=travel_total,
                total_service_minutes=service_total,
                end_minute=end_minute,
            )
        )

    unassigned = list(blocked) + [j.id for j in jobs if j.id not in assigned]
    job_mandatory = {j.id: j.mandatory for j in input_data.jobs}
    mandatory_left = [jid for jid in unassigned if job_mandatory.get(jid, False)]
    if mandatory_left:
        status = "infeasible"
        pre_messages = pre_messages + [
            f"Mandatory jobs not scheduled: {', '.join(mandatory_left)}"
        ]

    all_messages = pre_messages + preference_violations
    result = OptimizerResult(
        status=status,
        routes=routes,
        unassigned_job_ids=unassigned,
        objective_cost=int(total_objective),
        messages=all_messages,
    )
    if strict and status == "infeasible":
        raise InfeasibleScheduleError(result.messages, unassigned)
    return result

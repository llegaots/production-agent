"""OR-Tools VRP scheduler (pure Python, no database)."""

from app.optimizer.exceptions import InfeasibleScheduleError, OptimizerError
from app.optimizer.models import (
    CrewRoute,
    OptimizerInput,
    OptimizerResult,
    OptimizerStatus,
    RouteStop,
    ScheduleCrew,
    ScheduleJob,
    TimeWindow,
    TravelMatrix,
)
from app.optimizer.solver import solve

__all__ = [
    "CrewRoute",
    "InfeasibleScheduleError",
    "OptimizerError",
    "OptimizerInput",
    "OptimizerResult",
    "OptimizerStatus",
    "RouteStop",
    "ScheduleCrew",
    "ScheduleJob",
    "TimeWindow",
    "TravelMatrix",
    "solve",
]

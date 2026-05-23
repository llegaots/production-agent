"""Pydantic I/O for the isolated VRP optimizer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

OptimizerStatus = Literal["optimal", "feasible", "infeasible", "timeout"]


class TimeWindow(BaseModel):
    """Arrival window in minutes from the crew shift reference (same day)."""

    earliest_minute: int = Field(ge=0, description="Earliest arrival at the job site")
    latest_minute: int = Field(ge=0, description="Latest arrival at the job site")

    @model_validator(mode="after")
    def check_order(self) -> TimeWindow:
        if self.latest_minute < self.earliest_minute:
            raise ValueError("latest_minute must be >= earliest_minute")
        return self


class ScheduleCrew(BaseModel):
    id: str
    depot_index: int = Field(ge=0, description="Row/column index in the travel matrix")
    skills: list[str] = Field(default_factory=list)
    equipment_kinds: list[str] = Field(
        default_factory=list,
        description="Equipment kinds this crew carries (e.g. ladder_28, van)",
    )
    shift_start_minute: int = Field(default=0, ge=0)
    shift_end_minute: int = Field(default=480, ge=1)
    max_jobs: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_shift(self) -> ScheduleCrew:
        if self.shift_end_minute <= self.shift_start_minute:
            raise ValueError("shift_end_minute must be after shift_start_minute")
        return self


class ScheduleJob(BaseModel):
    id: str
    node_index: int = Field(ge=0, description="Row/column index in the travel matrix")
    service_minutes: int = Field(gt=0)
    time_window: TimeWindow
    required_skills: list[str] = Field(default_factory=list)
    required_equipment: list[str] = Field(default_factory=list)
    preferred_crew_id: str | None = None
    preference_penalty: int = Field(
        default=30,
        ge=0,
        description="Soft cost added when assigned to a non-preferred crew",
    )
    mandatory: bool = Field(
        default=True,
        description="If true, job must be scheduled or the run is infeasible",
    )


class TravelMatrix(BaseModel):
    """Square travel-time matrix in minutes between all nodes (depots + jobs)."""

    minutes: list[list[int]]

    @field_validator("minutes")
    @classmethod
    def validate_square(cls, value: list[list[int]]) -> list[list[int]]:
        if not value:
            raise ValueError("travel matrix must not be empty")
        n = len(value)
        for row in value:
            if len(row) != n:
                raise ValueError("travel matrix must be square")
            for cell in row:
                if cell < 0:
                    raise ValueError("travel times must be non-negative")
        return value

    @property
    def size(self) -> int:
        return len(self.minutes)


class OptimizerInput(BaseModel):
    crews: list[ScheduleCrew] = Field(min_length=1)
    jobs: list[ScheduleJob] = Field(default_factory=list)
    travel: TravelMatrix
    horizon_minutes: int = Field(default=600, ge=1)
    time_limit_seconds: int = Field(default=10, ge=1, le=300)
    unassigned_penalty: int = Field(
        default=10_000,
        ge=1,
        description="Penalty for dropping a non-mandatory job (unused if mandatory)",
    )

    @model_validator(mode="after")
    def check_indices(self) -> OptimizerInput:
        n = self.travel.size
        for crew in self.crews:
            if crew.depot_index >= n:
                raise ValueError(f"crew {crew.id} depot_index {crew.depot_index} out of range")
        for job in self.jobs:
            if job.node_index >= n:
                raise ValueError(f"job {job.id} node_index {job.node_index} out of range")
        return self


class RouteStop(BaseModel):
    job_id: str
    node_index: int
    arrival_minute: int
    start_minute: int
    depart_minute: int


class CrewRoute(BaseModel):
    crew_id: str
    stops: list[RouteStop] = Field(default_factory=list)
    total_travel_minutes: int = 0
    total_service_minutes: int = 0
    end_minute: int = 0


class OptimizerResult(BaseModel):
    status: OptimizerStatus
    routes: list[CrewRoute] = Field(default_factory=list)
    unassigned_job_ids: list[str] = Field(default_factory=list)
    objective_cost: int | None = None
    messages: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assigned_job_ids(self) -> list[str]:
        return [stop.job_id for route in self.routes for stop in route.stops]

    @property
    def is_success(self) -> bool:
        return self.status in ("optimal", "feasible") and not self.unassigned_job_ids

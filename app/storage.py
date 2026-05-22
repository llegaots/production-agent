"""Tiny in-memory store. Replace with a real DB when productionizing."""
from __future__ import annotations

from datetime import date
from threading import RLock
from typing import Optional

from .models import (
    Client,
    Crew,
    Equipment,
    Job,
    JobStatus,
    PlanResult,
    WeekPlan,
)
from .scheduling_prefs import DEFAULT_MODE, SchedulingMode


class Store:
    def __init__(self) -> None:
        self._lock = RLock()
        self.clients: dict[str, Client] = {}
        self.crews: dict[str, Crew] = {}
        self.equipment: dict[str, Equipment] = {}
        self.jobs: dict[str, Job] = {}
        self.latest_plan: Optional[PlanResult] = None
        self.confirmed_plan: Optional[PlanResult] = None
        self.scheduling_mode: SchedulingMode = DEFAULT_MODE
        self.last_plan_id: Optional[str] = None

    # ---- jobs ----
    def upsert_job(self, job: Job) -> Job:
        with self._lock:
            self.jobs[job.id] = job
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self.jobs.values())

    def set_job_status(self, job_id: str, status: JobStatus) -> Optional[Job]:
        with self._lock:
            j = self.jobs.get(job_id)
            if not j:
                return None
            j.status = status
            return j

    # ---- crews ----
    def list_crews(self) -> list[Crew]:
        return list(self.crews.values())

    def get_crew(self, crew_id: str) -> Optional[Crew]:
        return self.crews.get(crew_id)

    # ---- equipment ----
    def list_equipment(self) -> list[Equipment]:
        return list(self.equipment.values())

    def get_equipment(self, equipment_id: str) -> Optional[Equipment]:
        return self.equipment.get(equipment_id)

    # ---- clients ----
    def list_clients(self) -> list[Client]:
        return list(self.clients.values())

    def get_client(self, client_id: str) -> Optional[Client]:
        return self.clients.get(client_id)

    # ---- plan ----
    def set_plan(self, plan: PlanResult) -> None:
        with self._lock:
            self.latest_plan = plan

    def get_plan(self) -> Optional[PlanResult]:
        return self.latest_plan

    def set_confirmed_plan(self, plan: PlanResult) -> None:
        with self._lock:
            self.confirmed_plan = plan

    def get_confirmed_plan(self) -> Optional[PlanResult]:
        return self.confirmed_plan

    def find_job_day(self, job_id: str) -> Optional[date]:
        if not self.latest_plan:
            return None
        for d in self.latest_plan.plan.days:
            for s in d.stops:
                if s.job_id == job_id:
                    return d.day
        return None


store = Store()

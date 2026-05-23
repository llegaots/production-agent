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
)
from .scheduling_prefs import DEFAULT_MODE, SchedulingMode


class CrewUnavailability:
    """Records a date-range during which a crew (or its equipment) is unavailable."""

    def __init__(self, crew_id: str, start: date, end: date, reason: str = "") -> None:
        self.crew_id = crew_id
        self.start = start
        self.end = end
        self.reason = reason or "unavailable"

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


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
        # Crew unavailability periods (e.g. equipment failure, callout)
        self._unavailability: list[CrewUnavailability] = []

    # ---- crew unavailability ----
    def mark_crew_unavailable(
        self,
        crew_id: str,
        start: date,
        end: date,
        reason: str = "unavailable",
    ) -> None:
        """Mark a crew as unavailable for a date range (e.g. equipment failure)."""
        with self._lock:
            self._unavailability.append(CrewUnavailability(crew_id, start, end, reason))

    def clear_crew_unavailability(self, crew_id: Optional[str] = None) -> None:
        """Clear all unavailability records, or just those for a specific crew."""
        with self._lock:
            if crew_id is None:
                self._unavailability.clear()
            else:
                self._unavailability = [u for u in self._unavailability if u.crew_id != crew_id]

    def is_crew_available(self, crew_id: str, day: date) -> bool:
        """Return True if the crew has no unavailability record covering this day."""
        for u in self._unavailability:
            if u.crew_id == crew_id and u.covers(day):
                return False
        return True

    def get_unavailability_reason(self, crew_id: str, day: date) -> Optional[str]:
        """Return the reason for crew unavailability on a given day, or None."""
        for u in self._unavailability:
            if u.crew_id == crew_id and u.covers(day):
                return u.reason
        return None

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

"""Scheduling preferences — how the production manager prioritizes the week."""
from __future__ import annotations

from enum import Enum


class SchedulingMode(str, Enum):
    """How CrewMatch / GeoCluster weight the plan."""

    GEO_FIRST = "geo_first"  # minimize drive; tight geographic clusters (default)
    CREW_FILL = "crew_fill"  # pack crew-days toward capacity before spreading geographically
    BALANCED = "balanced"  # blend of utilization and proximity


DEFAULT_MODE = SchedulingMode.GEO_FIRST


def parse_mode(value: str | None) -> SchedulingMode:
    if not value:
        return DEFAULT_MODE
    v = value.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "geo": SchedulingMode.GEO_FIRST,
        "location": SchedulingMode.GEO_FIRST,
        "proximity": SchedulingMode.GEO_FIRST,
        "crew": SchedulingMode.CREW_FILL,
        "fill": SchedulingMode.CREW_FILL,
        "utilization": SchedulingMode.CREW_FILL,
        "pack": SchedulingMode.CREW_FILL,
        "balance": SchedulingMode.BALANCED,
        "balanced": SchedulingMode.BALANCED,
    }
    try:
        return SchedulingMode(v)
    except ValueError:
        return aliases.get(v, DEFAULT_MODE)


def placement_score_bonus(mode: SchedulingMode, remaining_minutes: int, drive_km: float) -> float:
    """Extra score term for crew/day candidate selection in CrewMatchAgent."""
    if mode == SchedulingMode.CREW_FILL:
        return 0.02 * remaining_minutes - 0.15 * drive_km
    if mode == SchedulingMode.BALANCED:
        return 0.008 * remaining_minutes - 0.08 * drive_km
    # geo_first: slight preference for headroom only when fit is equal
    return 0.003 * remaining_minutes - 0.2 * drive_km


def geo_cluster_target_cap(mode: SchedulingMode, max_slots: int, job_count: int) -> int:
    """How many geo clusters to aim for (fewer = larger routes, more crew-fill friendly)."""
    if mode == SchedulingMode.CREW_FILL:
        return min(job_count, max(1, max_slots // 2))
    if mode == SchedulingMode.BALANCED:
        return min(job_count, max_slots)
    return min(job_count, max_slots)

"""Scheduling preferences — how the production manager prioritizes the week."""
from __future__ import annotations

from enum import Enum


class SchedulingMode(str, Enum):
    """How CrewMatch / GeoCluster weight the plan.

    GEO_FIRST       — minimize drive time; tight geographic clusters (default).
                      Drive penalty is strongest; headroom bonus is weakest.

    CREW_FILL       — maximize utilization; pack crew-days toward capacity.
                      Fewer, larger clusters so each crew-day is well-filled.
                      Drive penalty is weakest; headroom bonus is strongest.

    BALANCED        — blend of utilization and proximity.
                      Intermediate cluster count and score weights.

    REVENUE_PRIORITY — schedule highest-value jobs first.
                      Clusters sorted by descending total revenue before
                      placement, so high-price jobs always get first pick of
                      available slots.  Score weights similar to BALANCED.
                      When capacity is tight, low-price jobs are deferred.
    """

    GEO_FIRST        = "geo_first"
    CREW_FILL        = "crew_fill"
    BALANCED         = "balanced"
    REVENUE_PRIORITY = "revenue_priority"


DEFAULT_MODE = SchedulingMode.GEO_FIRST


def parse_mode(value: str | None) -> SchedulingMode:
    if not value:
        return DEFAULT_MODE
    v = value.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "geo": SchedulingMode.GEO_FIRST,
        "location": SchedulingMode.GEO_FIRST,
        "location_optimized": SchedulingMode.GEO_FIRST,
        "proximity": SchedulingMode.GEO_FIRST,
        "crew": SchedulingMode.CREW_FILL,
        "fill": SchedulingMode.CREW_FILL,
        "packed": SchedulingMode.CREW_FILL,
        "packed_days": SchedulingMode.CREW_FILL,
        "utilization": SchedulingMode.CREW_FILL,
        "pack": SchedulingMode.CREW_FILL,
        "balance": SchedulingMode.BALANCED,
        "balanced": SchedulingMode.BALANCED,
        "balanced_workload": SchedulingMode.BALANCED,
        "revenue": SchedulingMode.REVENUE_PRIORITY,
        "priority": SchedulingMode.REVENUE_PRIORITY,
        "revenue_priority": SchedulingMode.REVENUE_PRIORITY,
        "value": SchedulingMode.REVENUE_PRIORITY,
        "high_value": SchedulingMode.REVENUE_PRIORITY,
    }
    try:
        return SchedulingMode(v)
    except ValueError:
        return aliases.get(v, DEFAULT_MODE)


# ── Placement score bonuses ────────────────────────────────────────────────────
#
# Applied inside CrewMatchAgent for each (crew, day) candidate.
# A higher score wins the slot.
#
# remaining_minutes : daily_minutes - minutes_already_used_this_day
# drive_km          : average distance from crew base to cluster centroid
#
# Key trade-off ratios:
#   GEO_FIRST        drive penalty = -0.200 / km   headroom = +0.003 / min
#   BALANCED         drive penalty = -0.080 / km   headroom = +0.008 / min
#   CREW_FILL        drive penalty = -0.150 / km   headroom = +0.020 / min
#   REVENUE_PRIORITY drive penalty = -0.080 / km   headroom = +0.008 / min
#
# The headroom bonus ensures that a slot with more available minutes is
# preferred when scores are otherwise equal.  In CREW_FILL the headroom
# bonus is much larger so the agent aggressively seeks out the emptiest
# day for each large cluster, which — combined with the reduced cluster
# count — leads to fewer, fuller crew-days.

def placement_score_bonus(mode: SchedulingMode, remaining_minutes: int, drive_km: float) -> float:
    """Extra score term for crew/day candidate selection in CrewMatchAgent."""
    if mode == SchedulingMode.CREW_FILL:
        # Prefer headroom strongly so large clusters land on the emptiest day.
        return 0.02 * remaining_minutes - 0.15 * drive_km
    if mode == SchedulingMode.BALANCED:
        return 0.008 * remaining_minutes - 0.08 * drive_km
    if mode == SchedulingMode.REVENUE_PRIORITY:
        # Same weights as BALANCED; ordering effect comes from cluster sort order.
        return 0.008 * remaining_minutes - 0.08 * drive_km
    # GEO_FIRST: drive proximity dominates; slight headroom tiebreak.
    return 0.003 * remaining_minutes - 0.2 * drive_km


# ── Cluster target cap ────────────────────────────────────────────────────────
#
# Controls how many geo-clusters GeoClusterAgent tries to produce.
# Fewer clusters → larger batches assigned to each crew-day → higher utilization.
# More clusters  → smaller, tighter-area batches → lower drive time per day.

def geo_cluster_target_cap(mode: SchedulingMode, max_slots: int, job_count: int) -> int:
    """How many geo clusters to aim for (fewer = larger routes, more crew-fill friendly)."""
    if mode == SchedulingMode.CREW_FILL:
        # Half as many clusters → each crew-day carries ~2× the work.
        return min(job_count, max(1, max_slots // 2))
    if mode == SchedulingMode.BALANCED:
        return min(job_count, max_slots)
    if mode == SchedulingMode.REVENUE_PRIORITY:
        # Same cluster structure as BALANCED; priority comes from sort order.
        return min(job_count, max_slots)
    # GEO_FIRST: maximum clusters for tightest geographic grouping.
    return min(job_count, max_slots)


def cluster_sort_key(
    mode: SchedulingMode,
    cluster_job_ids: list[str],
    jobs_by_id: dict,
) -> float:
    """Return a sort key for cluster ordering in CrewMatchAgent.

    Larger key = processed earlier (gets first pick of available slots).
    """
    if mode == SchedulingMode.REVENUE_PRIORITY:
        # Highest total revenue first.
        return sum(jobs_by_id[j].price for j in cluster_job_ids if j in jobs_by_id)
    # Default: heaviest cluster first (maximises chance of fitting large work).
    return sum(
        jobs_by_id[j].estimated_minutes for j in cluster_job_ids if j in jobs_by_id
    )

"""Scheduling preferences — how the production manager prioritizes the week."""
from __future__ import annotations

from datetime import date
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

# Mon→Fri front-fill: Monday gets (n_days-1)*weight, Friday gets 0.
# Strong enough to prefer earlier days when capacity exists, but not so
# large that it overrides hard trade-offs (drive, equipment, date windows).
WEEK_FILL_WEIGHT = 1.5


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


def load_balance_bonus(mode: SchedulingMode, crew_used_min: int, eligible_day_loads: list[int]) -> float:
    """Prefer underloaded crews on the same day (BALANCED mode only)."""
    if mode != SchedulingMode.BALANCED or not eligible_day_loads:
        return 0.0
    avg = sum(eligible_day_loads) / len(eligible_day_loads)
    # Strong enough to overcome moderate drive-distance bias when one crew is stacked.
    return 0.045 * (avg - crew_used_min)


def day_packing_bonus(crew_used_min: int, daily_minutes: int) -> float:
    """Prefer adding jobs to a crew-day that already has work (fill the truck).

    Best practice: pack each crew-day toward capacity before opening a new
    crew-day slot.  week_fill_bonus handles *which day* to start; this handles
    *continuing* to fill a day once started.
    """
    if crew_used_min <= 0:
        return 0.0
    remaining = daily_minutes - crew_used_min
    if remaining < 75:
        return 0.0
    return 5.0 + 0.018 * crew_used_min


def week_fill_bonus(
    week_start: date,
    day: date,
    *,
    n_days: int = 5,
    balance_day: date | None = None,
    crew_used_min: int = 0,
) -> float:
    """Prefer filling the planning week front-to-back (Mon → Fri).

    Default scheduling practice: pack the start of the week first, then spill
    to later days only when constraints require it (client date windows,
    crew capacity, equipment, location, load balancing, etc.).

    When the owner pins a balance day (reorganize), do not pull work earlier
    than that day — focus capacity on the requested date.

    Once a crew already has work on a day, day_packing_bonus continues that
    route — week fill does not apply to in-progress crew-days.
    """
    if crew_used_min > 0:
        return 0.0
    offset = (day - week_start).days
    if offset < 0 or offset >= n_days:
        return 0.0
    if balance_day is not None and day < balance_day:
        return 0.0
    return WEEK_FILL_WEIGHT * (n_days - 1 - offset)


def balance_day_bonus(balance_day: date | None, day: date) -> float:
    """Strong preference to populate the owner's target balance day."""
    if balance_day and day == balance_day:
        return 12.0
    return 0.0


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

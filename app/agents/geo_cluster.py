"""GeoClusterAgent - groups jobs by geographic proximity into day buckets.

Anthropic pattern: **Workflow step (prompt-chaining input)**.

This is the first step of the planning chain. It produces a deterministic,
geometric partitioning of the job backlog so downstream agents can reason
over coherent route-sized groups instead of N independent jobs.
"""
from __future__ import annotations

from .base import Agent, AgentContext, haversine_km, week_days


class GeoClusterAgent(Agent):
    """Greedy clustering of jobs so geographically-close jobs ride together.

    The output is placed on the context blackboard as ``geo_clusters``: a list
    of clusters, each a dict ``{"centroid": (lat, lng), "job_ids": [...]}``.

    A separate agent (CrewMatchAgent) decides which crew runs each cluster
    and which day it lands on.
    """

    name = "GeoClusterAgent"

    async def run(self, ctx: AgentContext) -> None:
        jobs = list(ctx.jobs)
        await ctx.emit(
            self.name,
            "start",
            f"Clustering {len(jobs)} pending jobs by location.",
        )

        # Aim for clusters of ~2-3 jobs (a typical half-day route). Cap by both
        # the number of jobs and the available crew-days so very small backlogs
        # don't spawn an absurd number of solo clusters.
        total_minutes = sum(j.estimated_minutes for j in jobs)
        avg_daily = (
            sum(c.daily_minutes for c in ctx.crews) / max(1, len(ctx.crews))
            if ctx.crews else 480
        )
        by_load = max(1, int(round(total_minutes / max(1, avg_daily))))
        by_count = max(1, (len(jobs) + 2) // 3)
        max_slots = max(1, len(ctx.crews) * len(week_days(ctx.week_start)))
        target_clusters = min(len(jobs), max_slots, max(by_load, by_count))
        clusters: list[dict] = []

        # seed with the geographically extreme jobs
        if not jobs:
            ctx.blackboard["geo_clusters"] = []
            await ctx.emit(self.name, "done", "No jobs to cluster.")
            return

        # 1. seed: pick the job furthest from the company centroid, then
        #    repeatedly pick the job furthest from any existing seed.
        avg_lat = sum(j.lat for j in jobs) / len(jobs)
        avg_lng = sum(j.lng for j in jobs) / len(jobs)
        remaining = jobs[:]
        seeds = []
        first = max(remaining, key=lambda j: haversine_km(avg_lat, avg_lng, j.lat, j.lng))
        seeds.append(first)
        remaining.remove(first)
        while len(seeds) < min(target_clusters, len(jobs)) and remaining:
            nxt = max(
                remaining,
                key=lambda j: min(haversine_km(s.lat, s.lng, j.lat, j.lng) for s in seeds),
            )
            seeds.append(nxt)
            remaining.remove(nxt)

        # 2. assign every job to its nearest seed
        buckets: list[list] = [[s] for s in seeds]
        for j in remaining:
            best = min(range(len(seeds)), key=lambda i: haversine_km(seeds[i].lat, seeds[i].lng, j.lat, j.lng))
            buckets[best].append(j)

        # 3. assemble clusters
        for b in buckets:
            if not b:
                continue
            clat = sum(j.lat for j in b) / len(b)
            clng = sum(j.lng for j in b) / len(b)
            clusters.append({"centroid": (clat, clng), "job_ids": [j.id for j in b]})

        ctx.blackboard["geo_clusters"] = clusters
        await ctx.emit(
            self.name,
            "done",
            f"Built {len(clusters)} geographic clusters from {len(jobs)} jobs.",
            detail={
                "clusters": [
                    {
                        "size": len(c["job_ids"]),
                        "job_ids": c["job_ids"],
                        "centroid": list(c["centroid"]),
                    }
                    for c in clusters
                ]
            },
        )

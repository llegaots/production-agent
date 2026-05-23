"""GeoClusterAgent - verify addresses via Google Geocoding, then cluster by proximity.

Anthropic pattern: **Workflow step (prompt-chaining input)**.

Phase A: geocode every job address (lat/lng + confidence + service-area check).
Phase B: greedy geographic clustering on verified coordinates.
"""
from __future__ import annotations

from ..geocode import GEOCODE_CONFIRM_THRESHOLD, geocoder
from ..scheduling_prefs import SchedulingMode, geo_cluster_target_cap
from ..storage import store
from ..supabase_store import persist_job_location
from .base import Agent, AgentContext, haversine_km, week_days


class GeoClusterAgent(Agent):
    """Geocode jobs, score address confidence, then cluster for routing."""

    name = "GeoClusterAgent"

    async def run(self, ctx: AgentContext) -> None:
        jobs = list(ctx.jobs)
        await ctx.emit_tool(
            "google_geocode",
            "invoke",
            f"Verifying {len(jobs)} job addresses via Google Geocoding"
            + ("" if geocoder.enabled else " (API key missing — using stored coordinates)."),
            {"job_count": len(jobs), "geocoder_enabled": geocoder.enabled},
        )
        await ctx.emit(
            self.name,
            "start",
            f"Geocoding and clustering {len(jobs)} jobs.",
        )

        verifications: dict[str, dict] = {}
        needs_review: list[str] = []

        for job in jobs:
            prior = (job.lat, job.lng)
            result = await geocoder.geocode(job.address)

            if result.success and result.lat is not None and result.lng is not None:
                job.lat = result.lat
                job.lng = result.lng
                if result.formatted_address:
                    job.address = result.formatted_address
                store.jobs[job.id] = job
                try:
                    await persist_job_location(
                        job.id,
                        job.lat,
                        job.lng,
                        job.address,
                        geocode_confidence=result.confidence,
                    )
                except Exception:
                    pass
            elif geocoder.enabled:
                result.issues.append("Keeping previous coordinates from database.")
                result.confidence = min(result.confidence, 0.45)
                result.needs_review = True

            verifications[job.id] = result.to_dict()
            if result.needs_review:
                needs_review.append(job.id)

            phase = "verified" if result.success and not result.needs_review else "review"
            msg = (
                f"{job.id}: {int(result.confidence * 100)}% confidence"
                f" — {result.formatted_address or job.address}"
            )
            if result.issues:
                msg += f" ({result.issues[0]})"

            await ctx.emit(
                self.name,
                phase,
                msg,
                detail={
                    "job_id": job.id,
                    "geocode": result.to_dict(),
                    "prior_coords": list(prior),
                    "coords": [job.lat, job.lng],
                },
                kind="data" if result.needs_review else "agent",
            )

        ctx.blackboard["geo_verifications"] = verifications
        ctx.blackboard["geo_needs_review"] = needs_review

        if needs_review:
            await ctx.emit(
                self.name,
                "warning",
                f"{len(needs_review)} job(s) below {int(GEOCODE_CONFIRM_THRESHOLD * 100)}% geocode confidence — confirm addresses before dispatch.",
                detail={"job_ids": needs_review},
            )

        # ---- clustering (uses updated lat/lng) ----
        jobs = list(ctx.jobs)
        await ctx.emit_tool(
            "geo_cluster",
            "invoke",
            f"Clustering {len(jobs)} jobs by verified coordinates (haversine farthest-first).",
            {"job_count": len(jobs), "needs_review": len(needs_review)},
        )

        mode: SchedulingMode = ctx.blackboard.get("scheduling_mode", ctx.scheduling_mode)
        total_minutes = sum(j.estimated_minutes for j in jobs)
        avg_daily = (
            sum(c.daily_minutes for c in ctx.crews) / max(1, len(ctx.crews))
            if ctx.crews else 480
        )
        by_load = max(1, int(round(total_minutes / max(1, avg_daily))))
        # Aim for fewer, larger clusters (~4 jobs each) so crew-days fill up.
        by_count = max(1, len(jobs) // max(4, len(ctx.crews) * 2))
        max_slots = max(1, len(ctx.crews) * len(week_days(ctx.week_start)))
        cap = geo_cluster_target_cap(mode, max_slots, len(jobs))
        target_clusters = min(len(jobs), max(by_load, by_count, 1), cap)
        clusters: list[dict] = []

        if not jobs:
            ctx.blackboard["geo_clusters"] = []
            await ctx.emit(self.name, "done", "No jobs to cluster.")
            return

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

        buckets: list[list] = [[s] for s in seeds]
        for j in remaining:
            best = min(
                range(len(seeds)),
                key=lambda i: haversine_km(seeds[i].lat, seeds[i].lng, j.lat, j.lng),
            )
            buckets[best].append(j)

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
            f"Geocoded {len(jobs)} addresses, built {len(clusters)} clusters"
            + (f" ({len(needs_review)} need address review)." if needs_review else "."),
            detail={
                "clusters": [
                    {
                        "size": len(c["job_ids"]),
                        "job_ids": c["job_ids"],
                        "centroid": list(c["centroid"]),
                    }
                    for c in clusters
                ],
                "geocode_review_count": len(needs_review),
            },
        )

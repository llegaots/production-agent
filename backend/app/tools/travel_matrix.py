from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.tools._db import tools_db
from app.tools.schemas import (
    GetTravelMatrixInput,
    GetTravelMatrixOutput,
    TravelNode,
)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _minutes_haversine_matrix(nodes: list[TravelNode]) -> list[list[int]]:
    n = len(nodes)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            km = _haversine_km(nodes[i].lat, nodes[i].lng, nodes[j].lat, nodes[j].lng)
            matrix[i][j] = max(1, int(km * 2.5))  # ~2.5 min/km driving estimate
    return matrix


def _fetch_google_matrix(api_key: str, nodes: list[TravelNode]) -> list[list[int]]:
    """Distance Matrix API — one row per origin (batched)."""
    n = len(nodes)
    matrix = [[0] * n for _ in range(n)]
    coords = [f"{node.lat},{node.lng}" for node in nodes]
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    with httpx.Client(timeout=30.0) as client:
        for i, origin in enumerate(coords):
            resp = client.get(
                url,
                params={
                    "origins": origin,
                    "destinations": "|".join(coords),
                    "mode": "driving",
                    "units": "metric",
                    "key": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "OK":
                raise RuntimeError(data.get("error_message", data.get("status")))
            elements = data["rows"][0]["elements"]
            for j, el in enumerate(elements):
                if el.get("status") == "OK":
                    matrix[i][j] = max(1, int(el["duration"]["value"] / 60))
                else:
                    matrix[i][j] = _minutes_haversine_matrix([nodes[i], nodes[j]])[0][1]
    return matrix


def _build_nodes(job_rows: list[dict], crew_rows: list[dict]) -> list[TravelNode]:
    nodes: list[TravelNode] = []
    idx = 0
    for crew in crew_rows:
        nodes.append(
            TravelNode(
                node_index=idx,
                ref_id=crew["id"],
                kind="depot",
                lat=float(crew["base_lat"]),
                lng=float(crew["base_lng"]),
            )
        )
        idx += 1
    for job in job_rows:
        nodes.append(
            TravelNode(
                node_index=idx,
                ref_id=job["id"],
                kind="job",
                lat=float(job["lat"]),
                lng=float(job["lng"]),
            )
        )
        idx += 1
    return nodes


def _cache_key(nodes: list[TravelNode]) -> str:
    payload = sorted(
        [
            {
                "ref": n.ref_id,
                "kind": n.kind,
                "lat": round(n.lat, 4),
                "lng": round(n.lng, 4),
            }
            for n in nodes
        ],
        key=lambda x: (x["kind"], x["ref"]),
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:40]


def _load_jobs_and_crews(inp: GetTravelMatrixInput) -> tuple[list[dict], list[dict]]:
    db = tools_db()
    jobs = db.table("jobs").select("id, lat, lng").in_("id", inp.job_ids).execute().data or []
    if len(jobs) != len(inp.job_ids):
        found = {j["id"] for j in jobs}
        missing = [j for j in inp.job_ids if j not in found]
        raise ValueError(f"Jobs not found: {missing}")

    cq = db.table("crews").select("id, base_lat, base_lng")
    if inp.crew_ids:
        cq = cq.in_("id", inp.crew_ids)
    crews = cq.execute().data or []
    if not crews:
        raise ValueError("No crews found for travel matrix")
    return jobs, crews


def get_travel_matrix(inp: GetTravelMatrixInput) -> GetTravelMatrixOutput:
    """NxN travel minutes; reads/writes Supabase cache before calling Google."""
    jobs, crews = _load_jobs_and_crews(inp)
    nodes = _build_nodes(jobs, crews)
    key = _cache_key(nodes)
    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()

    if not inp.force_refresh:
        cached = (
            tools_db()
            .table("travel_matrix_cache")
            .select("*")
            .eq("cache_key", key)
            .gt("expires_at", now)
            .limit(1)
            .execute()
            .data
        )
        if cached:
            row = cached[0]
            return GetTravelMatrixOutput(
                cache_key=key,
                nodes=[TravelNode.model_validate(n) for n in row["nodes"]],
                minutes=row["minutes"],
                provider="cache",
                cached=True,
            )

    provider: str
    if settings.google_maps_api_key:
        try:
            minutes = _fetch_google_matrix(settings.google_maps_api_key, nodes)
            provider = "google_maps"
        except Exception:
            minutes = _minutes_haversine_matrix(nodes)
            provider = "haversine"
    else:
        minutes = _minutes_haversine_matrix(nodes)
        provider = "haversine"

    expires = datetime.now(timezone.utc) + timedelta(hours=settings.travel_cache_ttl_hours)
    tools_db().table("travel_matrix_cache").upsert(
        {
            "cache_key": key,
            "nodes": [n.model_dump() for n in nodes],
            "minutes": minutes,
            "provider": provider,
            "expires_at": expires.isoformat(),
        }
    ).execute()

    return GetTravelMatrixOutput(
        cache_key=key,
        nodes=nodes,
        minutes=minutes,
        provider=provider,
        cached=False,
    )

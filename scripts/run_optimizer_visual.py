#!/usr/bin/env python3
"""
Run ONLY the schedule optimizer (no orchestrator / critic) and open an HTML report.

Examples:
  python scripts/run_optimizer_visual.py --date 2026-05-26
  python scripts/run_optimizer_visual.py --date 2026-05-26 --job-prefix intake-job- --limit 8
  python scripts/run_optimizer_visual.py --job-ids intake-job-abc,intake-job-def --open
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import get_settings  # noqa: E402
from app.tools import check_equipment, get_crew_availability, run_optimizer  # noqa: E402
from app.tools._db import tools_db  # noqa: E402
from app.tools.schemas import (  # noqa: E402
    CheckEquipmentInput,
    GetCrewAvailabilityInput,
    RunOptimizerInput,
)
from optimizer_visual_report import build_optimizer_html_report  # noqa: E402


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _load_job_ids(
    target: date,
    *,
    limit: int,
    job_prefix: str | None,
    explicit: list[str] | None,
) -> list[str]:
    if explicit:
        return explicit

    q = (
        tools_db()
        .table("jobs")
        .select("id")
        .eq("status", "pending")
        .lte("earliest_date", target.isoformat())
        .gte("latest_date", target.isoformat())
    )
    if job_prefix:
        q = q.like("id", f"{job_prefix}%")
    rows = q.order("id").limit(limit).execute().data or []
    return [r["id"] for r in rows]


def _load_job_meta(job_ids: list[str]) -> dict[str, dict]:
    if not job_ids:
        return {}
    rows = (
        tools_db()
        .table("jobs")
        .select("id, address, client_id, estimated_minutes, required_skills, required_equipment")
        .in_("id", job_ids)
        .execute()
        .data
        or []
    )
    return {r["id"]: r for r in rows}


def _load_crew_meta(crew_ids: list[str], avail: list) -> dict[str, dict]:
    names: dict[str, str] = {}
    if crew_ids:
        rows = (
            tools_db()
            .table("crews")
            .select("id, name")
            .in_("id", crew_ids)
            .execute()
            .data
            or []
        )
        names = {r["id"]: r.get("name") or r["id"] for r in rows}
    out: dict[str, dict] = {}
    for c in avail:
        out[c.crew_id] = {
            "name": names.get(c.crew_id, c.crew_id),
            "shift_start_minute": c.shift_start_minute,
            "shift_end_minute": c.shift_end_minute,
            "skills": c.skills,
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optimizer only and render HTML schedule.")
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=date.today(),
        help="Target scheduling day (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--job-ids",
        type=str,
        default="",
        help="Comma-separated job IDs (skips DB window query)",
    )
    parser.add_argument(
        "--job-prefix",
        type=str,
        default="",
        help="Only pending jobs whose id starts with this prefix",
    )
    parser.add_argument(
        "--crew-ids",
        type=str,
        default="",
        help="Comma-separated crew IDs (default: all available that day)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max jobs to load when --job-ids not set",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=0,
        help="OR-Tools seconds (default: OPTIMIZER_TIME_LIMIT_SECONDS from .env)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="HTML output path (default: evals/reports/optimizer_visual_<timestamp>.html)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the report in your default browser",
    )
    parser.add_argument(
        "--no-equipment-check",
        action="store_true",
        help="Skip equipment pre-check section in report",
    )
    args = parser.parse_args()

    settings = get_settings()
    target = args.date
    explicit = [j.strip() for j in args.job_ids.split(",") if j.strip()] or None
    job_prefix = args.job_prefix.strip() or None
    job_ids = _load_job_ids(target, limit=args.limit, job_prefix=job_prefix, explicit=explicit)

    if not job_ids:
        print(f"No pending jobs found for {target} (prefix={job_prefix!r}).")
        return 1

    crew_ids = [c.strip() for c in args.crew_ids.split(",") if c.strip()] or None
    avail = get_crew_availability(
        GetCrewAvailabilityInput(target_date=target, crew_ids=crew_ids),
    )
    resolved_crews = crew_ids or [c.crew_id for c in avail.crews if c.is_available]
    if not resolved_crews:
        print(f"No crews available on {target}.")
        return 1

    time_limit = args.time_limit or settings.optimizer_time_limit_seconds

    print(f"Target date: {target}")
    print(f"Jobs ({len(job_ids)}): {', '.join(job_ids[:6])}{'…' if len(job_ids) > 6 else ''}")
    print(f"Crews ({len(resolved_crews)}): {', '.join(resolved_crews[:6])}{'…' if len(resolved_crews) > 6 else ''}")
    print(f"Optimizer time limit: {time_limit}s")

    equip_out = None
    if not args.no_equipment_check:
        equip = check_equipment(
            CheckEquipmentInput(job_ids=job_ids, crew_ids=resolved_crews),
        )
        equip_out = equip.model_dump(mode="json")
        print(f"Equipment check: ok={equip.ok} conflicts={len(equip.conflicts)}")

    opt = run_optimizer(
        RunOptimizerInput(
            target_date=target,
            job_ids=job_ids,
            crew_ids=resolved_crews,
            time_limit_seconds=time_limit,
        )
    )

    result = opt.result
    print(
        f"Result: status={result.status} assigned={len(result.assigned_job_ids)} "
        f"unassigned={len(result.unassigned_job_ids)}"
    )
    for route in result.routes:
        if route.stops:
            stop_ids = " → ".join(s.job_id for s in route.stops)
            print(f"  {route.crew_id}: {stop_ids}")

    job_meta = _load_job_meta(job_ids)
    crew_meta = _load_crew_meta(resolved_crews, avail.crews)
    html = build_optimizer_html_report(
        opt=opt,
        target_date=target,
        job_meta=job_meta,
        crew_meta=crew_meta,
        equipment_check=equip_out,
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.output or (ROOT / "evals" / "reports" / f"optimizer_visual_{ts}.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\nWrote: {out_path.resolve()}")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())

    return 0 if result.assigned_job_ids else 1


if __name__ == "__main__":
    raise SystemExit(main())

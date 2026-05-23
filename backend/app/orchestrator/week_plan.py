"""Multi-day job partitioning for programmatic week scheduling."""

from __future__ import annotations

from datetime import date, timedelta

from app.tools._db import tools_db


def load_job_date_windows(job_ids: list[str]) -> dict[str, tuple[date, date]]:
    if not job_ids:
        return {}
    rows = (
        tools_db()
        .table("jobs")
        .select("id, earliest_date, latest_date")
        .in_("id", job_ids)
        .execute()
        .data
        or []
    )
    out: dict[str, tuple[date, date]] = {}
    for row in rows:
        out[row["id"]] = (
            date.fromisoformat(str(row["earliest_date"])),
            date.fromisoformat(str(row["latest_date"])),
        )
    return out


def eligible_jobs_for_day(
    job_ids: list[str],
    day: date,
    *,
    windows: dict[str, tuple[date, date]] | None = None,
    limit: int = 15,
) -> list[str]:
    """Jobs whose date window includes ``day``, capped per optimizer run."""
    windows = windows or load_job_date_windows(job_ids)
    eligible: list[str] = []
    for jid in job_ids:
        earliest, latest = windows.get(jid, (day, day))
        if earliest <= day <= latest:
            eligible.append(jid)
        if len(eligible) >= limit:
            break
    return eligible


def iter_week_days(week_start: date, week_end: date):
    """Mon–Fri scheduling days within the mission window."""
    day = week_start
    while day <= week_end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)

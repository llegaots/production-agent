"""
Golden-set evaluation CLI.

  python -m evals.golden mark {schedule_id}
  python -m evals.golden run [--schedule-id UUID]
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "evals" / "reports"


def cmd_mark(schedule_id: str) -> int:
    from app.schedules.snapshot import mark_schedule_golden

    row = mark_schedule_golden(UUID(schedule_id))
    print(
        f"Marked golden: schedule_id={row['id']} "
        f"jobs={len(row.get('job_ids') or [])} "
        f"drive={row.get('total_drive_minutes')}min "
        f"pref_viol={row.get('preference_violations')}",
        flush=True,
    )
    return 0


def _load_replay_assignments(result, target_date: date):
    from app.tools._db import tools_db
    from evals.golden_compare import ScheduleAssignments

    from evals.metrics import final_attempt_id

    attempt_id = final_attempt_id(result)
    if not attempt_id:
        return ScheduleAssignments(by_job={})
    row = (
        tools_db()
        .table("schedule_attempts")
        .select("optimizer_result")
        .eq("id", attempt_id)
        .single()
        .execute()
        .data
    )
    return ScheduleAssignments.from_optimizer_result(
        row.get("optimizer_result") or {},
        target_date=target_date,
    )


def _replay_golden_schedule(row: dict) -> tuple:
    from app.orchestrator.runner import run_scheduling_mission
    from app.orchestrator.schemas import ScheduleWeekInput
    from evals.metrics import collect_trial_metrics

    target = date.fromisoformat(str(row["target_date"]))
    week_start = date.fromisoformat(str(row["week_start"]))
    week_end = date.fromisoformat(str(row["week_end"]))
    job_ids = list(row.get("job_ids") or [])
    crew_ids = list(row.get("crew_ids") or [])

    result = run_scheduling_mission(
        ScheduleWeekInput(
            user_request=row.get("user_request")
            or "Golden set replay: re-schedule the same jobs and crews.",
            week_start=week_start,
            week_end=week_end,
            target_date=target,
            job_ids=job_ids,
            crew_ids=crew_ids or None,
            job_load_limit=len(job_ids) if job_ids else None,
            max_iterations=4,
            use_llm_critic=False,
            use_agent=False,
        )
    )
    replay_assignments = _load_replay_assignments(result, target)
    replay_metrics = collect_trial_metrics(result, iteration_cap=4)
    return result, replay_assignments, replay_metrics


def cmd_run(*, schedule_id: str | None, persist: bool) -> int:
    from app.tools._db import tools_db
    from evals.golden_compare import compare_to_golden
    from evals.golden_report import golden_report_path, golden_report_timestamp, render_golden_report

    db = tools_db()
    q = db.table("schedules").select("*").eq("golden", True)
    if schedule_id:
        q = q.eq("id", schedule_id)
    golden_rows = q.order("golden_marked_at", desc=True).execute().data or []

    if not golden_rows:
        print("No golden schedules found. Mark approved schedules with: evals.golden mark <id>")
        return 0

    eval_batch_id = uuid.uuid4()
    ts = golden_report_timestamp()
    out_path = golden_report_path(REPORTS_DIR, ts)
    results = []

    print(f"Evaluating {len(golden_rows)} golden schedule(s)…", flush=True)
    for row in golden_rows:
        sid = row["id"]
        print(f"  replay {sid}…", flush=True)
        result, replay_assignments, replay_metrics = _replay_golden_schedule(row)
        drift = compare_to_golden(
            row,
            result,
            replay_assignments=replay_assignments,
            replay_metrics=replay_metrics,
        )
        results.append(drift)
        print(
            f"    same_crew={drift.same_crew_pct:.1f}% same_day={drift.same_day_pct:.1f}% "
            f"drive_Δ={drift.drive_minutes_delta:+d} pref_Δ={drift.preference_violations_delta:+d}",
            flush=True,
        )

        if persist:
            db.table("golden_eval_runs").insert(
                {
                    "eval_batch_id": str(eval_batch_id),
                    "report_path": str(out_path.relative_to(ROOT)),
                    "schedule_id": sid,
                    "replay_schedule_run_id": str(result.schedule_run_id),
                    "same_crew_pct": drift.same_crew_pct,
                    "same_day_pct": drift.same_day_pct,
                    "drive_minutes_delta": drift.drive_minutes_delta,
                    "preference_violations_delta": drift.preference_violations_delta,
                    "metrics": drift.as_dict(),
                }
            ).execute()

    body = render_golden_report(
        eval_batch_id=eval_batch_id,
        timestamp=ts,
        results=results,
    )
    out_path.write_text(body, encoding="utf-8")
    print(f"\nReport: {out_path}", flush=True)
    print(f"Batch ID: {eval_batch_id}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden-set schedule evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    mark_p = sub.add_parser("mark", help="Mark a dispatcher-approved schedule as golden")
    mark_p.add_argument("schedule_id", help="schedule_runs / schedules UUID")

    run_p = sub.add_parser(
        "run",
        help="Replay orchestrator for golden schedules and report drift",
    )
    run_p.add_argument(
        "--schedule-id",
        default=None,
        help="Evaluate one golden schedule (default: all golden)",
    )
    run_p.add_argument(
        "--no-persist",
        action="store_true",
        help="Skip writing golden_eval_runs rows",
    )

    args = parser.parse_args(argv)
    if args.command == "mark":
        return cmd_mark(args.schedule_id)
    if args.command == "run":
        return cmd_run(schedule_id=args.schedule_id, persist=not args.no_persist)
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Markdown reports for golden-set drift evals."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from evals.golden_compare import GoldenDriftMetrics


def golden_report_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def golden_report_path(reports_dir: Path, timestamp: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"golden_{timestamp}.md"


def render_golden_report(
    *,
    eval_batch_id: UUID,
    timestamp: str,
    results: list[GoldenDriftMetrics],
) -> str:
    lines = [
        "# Golden set drift report",
        "",
        f"- **Batch ID:** `{eval_batch_id}`",
        f"- **Generated (UTC):** {timestamp}",
        f"- **Golden schedules evaluated:** {len(results)}",
        "",
        "_Drift metrics compare a fresh orchestrator replay to the dispatcher-approved "
        "golden snapshot. Different but valid schedules are expected; this tracks regression._",
        "",
        "## Summary",
        "",
        "| Schedule ID | Same crew % | Same day % | Drive Δ (min) | Pref viol Δ | "
        "Replay status | Replay iters |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]

    if not results:
        lines.append("| _none_ | — | — | — | — | — | — |")
    else:
        for r in results:
            lines.append(
                f"| `{r.schedule_id[:8]}…` | {r.same_crew_pct:.1f}% | {r.same_day_pct:.1f}% | "
                f"{r.drive_minutes_delta:+d} | {r.preference_violations_delta:+d} | "
                f"{r.replay_status} | {r.replay_iteration_count} |"
            )

    lines.extend(
        [
            "",
            "**Drive Δ** = replay total drive − golden total drive (all crews).  ",
            "**Pref viol Δ** = replay preference violations − golden (from critic metrics).",
            "",
        ]
    )

    for r in results:
        lines.extend(
            [
                f"## Schedule `{r.schedule_id}`",
                "",
                f"- Golden jobs: **{r.golden_job_count}** (assigned in golden: **{r.golden_assigned_count}**)",
                f"- Replay assigned: **{r.replay_assigned_count}**",
                f"- Golden drive: **{r.golden_drive_minutes}** min → replay: **{r.replay_drive_minutes}** min "
                f"(Δ **{r.drive_minutes_delta:+d}**)",
                f"- Golden pref violations: **{r.golden_preference_violations}** → replay: "
                f"**{r.replay_preference_violations}** (Δ **{r.preference_violations_delta:+d}**)",
                f"- Same crew: **{r.same_crew_pct:.1f}%** | Same day: **{r.same_day_pct:.1f}%**",
                "",
            ]
        )
        if r.crew_mismatches:
            lines.append("### Crew mismatches (sample)")
            lines.append("")
            lines.append("| Job | Golden crew | Replay crew |")
            lines.append("| --- | --- | --- |")
            for m in r.crew_mismatches[:10]:
                lines.append(
                    f"| `{m['job_id']}` | {m['golden_crew']} | {m['replay_crew']} |"
                )
            lines.append("")
        if r.day_mismatches:
            lines.append("### Day mismatches (sample)")
            lines.append("")
            lines.append("| Job | Golden day | Replay day |")
            lines.append("| --- | --- | --- |")
            for m in r.day_mismatches[:10]:
                lines.append(f"| `{m['job_id']}` | {m['golden_day']} | {m['replay_day']} |")
            lines.append("")

    return "\n".join(lines)

"""Markdown report generation for eval batches."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from evals.metrics import TrialMetrics
from evals.stats import ScenarioAggregate


def report_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def report_path(reports_dir: Path, timestamp: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"{timestamp}.md"


def render_report(
    *,
    eval_batch_id: UUID,
    timestamp: str,
    aggregates: list[ScenarioAggregate],
    trial_rows: dict[str, list[TrialMetrics]],
    iterations_per_scenario: int,
    use_agent: bool,
    agent_mode_label: str = "",
) -> str:
    mode = agent_mode_label or ("Anthropic tool-use" if use_agent else "programmatic")
    lines = [
        "# Orchestrator eval report",
        "",
        f"- **Batch ID:** `{eval_batch_id}`",
        f"- **Generated (UTC):** {timestamp}",
        f"- **Trials per scenario:** {iterations_per_scenario}",
        f"- **Agent mode:** {mode}",
        "",
        "## Summary",
        "",
        "| Scenario | Trials | Approval rate | Approval var | Avg iterations | Iter var | "
        "Avg drive (min) | Drive var | Avg pref viol | Pref var |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for agg in aggregates:
        lines.append(agg.as_markdown_row())

    lines.extend(
        [
            "",
            "_Approval rate: % of trials with `approved` and `iteration_count` ≤ scenario orchestrator cap._",
            "_Variance: sample variance across trials (0 when trials < 2)._",
            "",
        ]
    )

    for agg in aggregates:
        trials = trial_rows.get(agg.scenario_name, [])
        lines.extend(
            [
                f"## {agg.scenario_name}",
                "",
                f"Iteration cap: **{agg.iteration_cap}**",
                "",
                "| Trial | Status | Approved | Within cap | Iterations | Drive (min) | Pref viol |",
                "| ---: | --- | :---: | :---: | ---: | ---: | ---: |",
            ]
        )
        for i, t in enumerate(trials, start=1):
            lines.append(
                f"| {i} | {t.status} | {'yes' if t.approved else 'no'} | "
                f"{'yes' if t.approved_within_cap else 'no'} | {t.iteration_count} | "
                f"{t.total_drive_minutes} | {t.preference_violations} |"
            )
        lines.append("")

    return "\n".join(lines)

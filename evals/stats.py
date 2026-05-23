"""Aggregate statistics across repeated eval trials."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from evals.metrics import TrialMetrics


@dataclass(frozen=True)
class ScenarioAggregate:
    scenario_name: str
    trials: int
    iteration_cap: int
    approval_rate_pct: float
    approval_rate_variance: float
    avg_iteration_count: float
    iteration_count_variance: float
    avg_total_drive_minutes: float
    total_drive_minutes_variance: float
    avg_preference_violations: float
    preference_violations_variance: float

    def as_markdown_row(self) -> str:
        return (
            f"| {self.scenario_name} | {self.trials} | "
            f"{self.approval_rate_pct:.1f}% | {self.approval_rate_variance:.4f} | "
            f"{self.avg_iteration_count:.2f} | {self.iteration_count_variance:.4f} | "
            f"{self.avg_total_drive_minutes:.1f} | {self.total_drive_minutes_variance:.2f} | "
            f"{self.avg_preference_violations:.2f} | {self.preference_violations_variance:.4f} |"
        )


def _sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.variance(values))


def aggregate_scenario(
    scenario_name: str,
    trials: list[TrialMetrics],
    *,
    iteration_cap: int,
) -> ScenarioAggregate:
    n = len(trials)
    approval_flags = [1.0 if t.approved_within_cap else 0.0 for t in trials]
    iterations = [float(t.iteration_count) for t in trials]
    drive = [float(t.total_drive_minutes) for t in trials]
    prefs = [float(t.preference_violations) for t in trials]

    approval_rate = (sum(approval_flags) / n * 100.0) if n else 0.0

    return ScenarioAggregate(
        scenario_name=scenario_name,
        trials=n,
        iteration_cap=iteration_cap,
        approval_rate_pct=approval_rate,
        approval_rate_variance=_sample_variance(approval_flags),
        avg_iteration_count=statistics.mean(iterations) if iterations else 0.0,
        iteration_count_variance=_sample_variance(iterations),
        avg_total_drive_minutes=statistics.mean(drive) if drive else 0.0,
        total_drive_minutes_variance=_sample_variance(drive),
        avg_preference_violations=statistics.mean(prefs) if prefs else 0.0,
        preference_violations_variance=_sample_variance(prefs),
    )

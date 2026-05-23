"""Shared assertions for orchestrator E2E scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.critic.schemas import CriticIssue
from app.orchestrator.schemas import ScheduleRunResult
from app.tools._db import tools_db

if TYPE_CHECKING:
    from tests.e2e.scenario_loader import OrchestratorScenario, ScenarioExpect


def _load_final_attempt(result: ScheduleRunResult) -> dict | None:
    attempt_id = result.final_schedule_attempt_id
    if not attempt_id and result.iterations:
        attempt_id = result.iterations[-1].schedule_attempt_id
    if not attempt_id:
        return None
    row = (
        tools_db()
        .table("schedule_attempts")
        .select("optimizer_result, job_ids")
        .eq("id", str(attempt_id))
        .single()
        .execute()
        .data
    )
    return row


def _collect_critic_issues(result: ScheduleRunResult) -> list[CriticIssue]:
    issues: list[CriticIssue] = []
    for iteration in result.iterations:
        if not iteration.critic_feedback_id:
            continue
        row = (
            tools_db()
            .table("critic_feedback")
            .select("metrics")
            .eq("id", str(iteration.critic_feedback_id))
            .single()
            .execute()
            .data
        )
        metrics = row.get("metrics") or {}
        for raw in metrics.get("structured_issues") or []:
            issues.append(CriticIssue.model_validate(raw))
    return issues


def assert_final_status(result: ScheduleRunResult, expect: ScenarioExpect) -> None:
    assert result.status == expect.status, (
        f"status={result.status!r}, expected {expect.status!r}"
    )


def assert_iteration_cap(result: ScheduleRunResult, *, orchestrator_cap: int) -> None:
    assert result.iteration_count <= orchestrator_cap, (
        f"iteration_count={result.iteration_count} exceeds orchestrator cap {orchestrator_cap}"
    )


def assert_approval_iteration_bound(
    result: ScheduleRunResult,
    expect: ScenarioExpect,
) -> None:
    if expect.status != "approved":
        return
    assert result.approved, "expected approved status"
    assert result.iteration_count <= expect.max_iterations, (
        f"approved in {result.iteration_count} iterations, "
        f"expected <= {expect.max_iterations}"
    )
    if expect.min_iterations > 1:
        assert result.iteration_count >= expect.min_iterations, (
            f"expected at least {expect.min_iterations} iterations, got {result.iteration_count}"
        )


def assert_no_high_critic_issues(
    result: ScheduleRunResult,
    expect: ScenarioExpect,
) -> None:
    high = [
        issue
        for issue in _collect_critic_issues(result)
        if issue.severity in ("high", "critical")
    ]
    cap = expect.max_high_severity_issues
    if cap >= 999:
        return
    assert len(high) <= cap, f"high/critical critic issues: {[i.model_dump() for i in high]}"


def assert_jobs_accounted(
    result: ScheduleRunResult,
    *,
    expected_job_ids: set[str],
    expect: ScenarioExpect,
) -> None:
    if not expect.require_all_jobs_accounted:
        return

    attempt = _load_final_attempt(result)
    assert attempt is not None, "no schedule attempt persisted for final iteration"

    opt = attempt.get("optimizer_result") or {}
    scheduled: set[str] = set(opt.get("assigned_job_ids") or [])
    for route in opt.get("routes") or []:
        for stop in route.get("stops") or []:
            if stop.get("job_id"):
                scheduled.add(stop["job_id"])
    deferred: set[str] = set(opt.get("unassigned_job_ids") or [])

    accounted = scheduled | deferred
    missing = expected_job_ids - accounted
    extra = accounted - expected_job_ids
    assert not missing, f"jobs missing from schedule/deferred: {missing}"
    assert not extra, f"unexpected job ids in output: {extra}"

    if not expect.allow_unassigned and deferred:
        pytest_fail = f"unexpected deferred/unassigned jobs: {deferred}"
        raise AssertionError(pytest_fail)


def log_langfuse_on_failure(result: ScheduleRunResult, *, scenario: str) -> None:
    if result.langfuse_trace_id:
        print(f"[e2e:{scenario}] langfuse_trace_id={result.langfuse_trace_id}")


def assert_scenario_result(
    result: ScheduleRunResult,
    scenario: OrchestratorScenario,
) -> None:
    assert_final_status(result, scenario.expect)
    assert_iteration_cap(result, orchestrator_cap=scenario.max_iterations)
    assert_approval_iteration_bound(result, scenario.expect)
    assert_no_high_critic_issues(result, scenario.expect)
    assert_jobs_accounted(
        result,
        expected_job_ids=set(scenario.all_job_ids),
        expect=scenario.expect,
    )
